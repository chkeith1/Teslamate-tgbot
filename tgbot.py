import os
import paho.mqtt.client as mqtt
import telegram
from telegram import ParseMode
import logging
from datetime import datetime
import math
from typing import Union
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

CONFIG = {
    "car_id": os.getenv("CAR_ID", "1"),
    "telegram_chat_id": os.getenv("TELEGRAM_BOT_CHAT_ID"),
    "telegram_bot_api_key": os.getenv("TELEGRAM_BOT_API_KEY"),
    "mqtt_broker_host": os.getenv("MQTT_BROKER_HOST"),
    "mqtt_broker_port": int(os.getenv("MQTT_BROKER_PORT", "1883")),
    "mqtt_broker_username": os.getenv("MQTT_BROKER_USERNAME"),
    "mqtt_broker_password": os.getenv("MQTT_BROKER_PASSWORD"),
    "units": os.getenv("UNITS", "Km").lower(),
    "timestamp_position": os.getenv("TIMESTAMP", "bottom").lower(),
    "debug": os.getenv("DEBUG", "False").lower() == "true",
}

if not all([CONFIG["telegram_chat_id"], CONFIG["telegram_bot_api_key"]]):
    logging.error("Missing required Telegram environment variables!")
    exit(1)

if CONFIG["units"] in ["metric", "km"]:
    CONFIG["units"] = "Km"
elif CONFIG["units"] in ["imperial", "miles"]:
    CONFIG["units"] = "Miles"

MESSAGES = {
    "success": "✔️ Successfully connected to MQTT broker",
    "version": "Version 20250505-01",
    "broker_failed": "❌ Failed to connect to MQTT broker",
    "state_online": "📶 Car Online",
    "state_asleep": "💤 Car Asleep",
    "state_suspended": "🛏️ Trying to sleep",
    "state_charging": "🔌 Car Charging",
    "state_offline": "🛰️ Car Disconnected",
    "state_start": "🚀 Car Starting",
    "state_driving": "🏁 Car Driving",
    "state_unknown": "⭕ Unknown State",
    "hour": "Hour",
    "minute": "Minute",
    "charge_ended": "✅ Charge Ended",
    "car_locked": "🔒 Car Locked",
    "car_unlocked": "🔓 Car Unlocked",
    "low_battery": "Low battery!!",
    "windows_opened": "🪟 Windows Open",
    "windows_closed": "✅ Windows Closed",
    "trunk_opened": "🧳 Trunk Open",
    "trunk_closed": "✅ Trunk Closed",
    "frunk_opened": "🧳 Frunk Open",
    "frunk_closed": "✅ Frunk Closed",
    "unknown": "❔",
}

MODEL_MAP = {
    "S": "Model S",
    "3": "Model 3",
    "X": "Model X",
    "Y": "Model Y",
}

MIN_BATTERY_LEVEL = 20

class VehicleState:
    def __init__(self):
        self.car_name = MESSAGES["unknown"]
        self.car_model = MESSAGES["unknown"]
        self.odometer_reading = 0.0
        self.locked = MESSAGES["unknown"]
        self.state = MESSAGES["unknown"]
        self.windows_open = MESSAGES["unknown"]
        self.trunk_open = MESSAGES["unknown"]
        self.frunk_open = MESSAGES["unknown"]
        self.update_available = False
        self.previous_update_available = False
        self.battery_level = -1.0
        self.est_range = -1.0
        self.charge_energy_added = 0.0
        self.charge_session_kwh = 0.0  
        self.charger_power = 0.0
        self.charger_current = 0.0
        self.time_to_full_charge = 0.0
        self.charge_ended = False
        self.new_info_available = False
        self.last_charging_update_time = 0
        self.charging_start_time = 0
        self.charging_start_kwh = 0.0 

vehicle_state = VehicleState()

bot = telegram.Bot(token=CONFIG["telegram_bot_api_key"])

def pluralize(word: str, count: float) -> str:
    return f"{word}{'s' if count != 1 else ''}"

def get_state_message(state: str) -> str:
    if state == MESSAGES["unknown"]:
        return MESSAGES["unknown"]
    state_map = {
        "online": MESSAGES["state_online"],
        "asleep": MESSAGES["state_asleep"],
        "suspended": MESSAGES["state_suspended"],
        "charging": MESSAGES["state_charging"],
        "offline": MESSAGES["state_offline"],
        "start": MESSAGES["state_start"],
        "driving": MESSAGES["state_driving"],
    }
    return state_map.get(state, MESSAGES["state_unknown"])

def get_model_name(model: str) -> str:
    if model == MESSAGES["unknown"]:
        return MESSAGES["unknown"]
    return MODEL_MAP.get(model, model)

def get_status_message(value: Union[str, bool], opened_msg: str, closed_msg: str) -> str:
    if value == MESSAGES["unknown"]:
        return MESSAGES["unknown"]
    return opened_msg if value else closed_msg

def send_telegram_message(message: str) -> None:
    try:
        bot.send_message(chat_id=CONFIG["telegram_chat_id"], text=message, parse_mode=ParseMode.HTML)
        if CONFIG["debug"]:
            logging.info(f"Message sent to Telegram:\n{'-'*40}\n{message}\n{'-'*40}")
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT broker")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/display_name")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/model")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/odometer")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/locked")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/state")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/windows_open")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/trunk_open")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/frunk_open")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/update_available")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/usable_battery_level")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/est_battery_range_km")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/charge_energy_added")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/charger_power")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/charger_actual_current")
        client.subscribe(f"teslamate/cars/{CONFIG['car_id']}/time_to_full_charge")
        message = f"{MESSAGES['success']}\n{MESSAGES['version']}"
        send_telegram_message(message)
    else:
        logging.error(f"Failed to connect to MQTT broker with code: {rc}")
        send_telegram_message(MESSAGES["broker_failed"])

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = str(msg.payload.decode())
    
    if topic == f"teslamate/cars/{CONFIG['car_id']}/display_name":
        vehicle_state.car_name = payload
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/model":
        vehicle_state.car_model = payload
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/odometer":
        vehicle_state.odometer_reading = float(payload)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/locked":
        new_locked = payload == "true"
        if vehicle_state.locked != new_locked:
            vehicle_state.new_info_available = True
        vehicle_state.locked = new_locked
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/state":
        new_state = payload
        if vehicle_state.state == "charging" and new_state != "charging":
            vehicle_state.charge_session_kwh = 0.0
            vehicle_state.charging_start_time = 0
            vehicle_state.charging_start_kwh = 0.0
        if new_state == "charging":
            vehicle_state.charging_start_time = time.time()
            vehicle_state.charging_start_kwh = vehicle_state.charge_energy_added
            vehicle_state.charge_session_kwh = 0.0
        if vehicle_state.state != new_state:
            vehicle_state.new_info_available = True
        vehicle_state.state = new_state
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/windows_open":
        vehicle_state.windows_open = payload == "true"
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/trunk_open":
        vehicle_state.trunk_open = payload == "true"
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/frunk_open":
        vehicle_state.frunk_open = payload == "true"
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/update_available":
        new_update_available = payload == "true"
        if new_update_available and not vehicle_state.previous_update_available:
            message = f"🚗 {vehicle_state.car_name} ({get_model_name(vehicle_state.car_model)})\n🎁 An update is available"
            send_telegram_message(message)
        vehicle_state.update_available = new_update_available
        vehicle_state.previous_update_available = new_update_available
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/usable_battery_level":
        vehicle_state.battery_level = float(payload)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/est_battery_range_km":
        vehicle_state.est_range = float(payload)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/charge_energy_added":
        vehicle_state.charge_energy_added = float(payload)
        if vehicle_state.state == "charging" and vehicle_state.time_to_full_charge > 0:
            vehicle_state.charge_session_kwh = max(vehicle_state.charge_energy_added - vehicle_state.charging_start_kwh, 0)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/charger_power":
        vehicle_state.charger_power = float(payload)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/charger_actual_current":
        vehicle_state.charger_current = float(payload)
    elif topic == f"teslamate/cars/{CONFIG['car_id']}/time_to_full_charge":
        new_time_to_full_charge = float(payload)
        if new_time_to_full_charge > 0:
            if vehicle_state.time_to_full_charge == 0:
                vehicle_state.charging_start_time = time.time()
                vehicle_state.charging_start_kwh = vehicle_state.charge_energy_added
                vehicle_state.charge_session_kwh = 0.0
            vehicle_state.time_to_full_charge = new_time_to_full_charge
            if vehicle_state.state == "charging":
                current_time = time.time()
                if current_time - vehicle_state.last_charging_update_time >= 300:
                    vehicle_state.new_info_available = True
                    vehicle_state.last_charging_update_time = current_time
        elif new_time_to_full_charge == 0:
            vehicle_state.time_to_full_charge = 0
            if vehicle_state.charge_session_kwh > 0:
                current_time = time.time()
                duration_seconds = current_time - vehicle_state.charging_start_time
                hours = duration_seconds / 3600
                hours_display = f"{hours:.1f}"
                message = f"🔌 Charging Ended\n⚡ {vehicle_state.charge_session_kwh:.2f} kWh Added\n⏰ Charged for {hours_display}hrs"
                send_telegram_message(message)
            vehicle_state.charge_session_kwh = 0.0
            vehicle_state.charging_start_time = 0
            vehicle_state.charging_start_kwh = vehicle_state.charge_energy_added

    if vehicle_state.new_info_available:
        send_formatted_message()
        vehicle_state.new_info_available = False

def send_formatted_message():
    timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    message = []
    if CONFIG["timestamp_position"] == "top":
        message.append(f"{timestamp}\n")
    message.extend([
        f"🚗 {vehicle_state.car_name} ({get_model_name(vehicle_state.car_model)}) {vehicle_state.odometer_reading:.2f} km",
        f"{'🔒 Car Locked' if vehicle_state.locked == True else '🔓 Car Unlocked' if vehicle_state.locked == False else '❔'}",
        get_state_message(vehicle_state.state),
        get_status_message(vehicle_state.windows_open, MESSAGES["windows_opened"], MESSAGES["windows_closed"]),
        get_status_message(vehicle_state.trunk_open, MESSAGES["trunk_opened"], MESSAGES["trunk_closed"]),
        get_status_message(vehicle_state.frunk_open, MESSAGES["frunk_opened"], MESSAGES["frunk_closed"]),
    ])
    
    if vehicle_state.update_available:
        message.append("🎁 An update is available")
    
    if vehicle_state.battery_level > MIN_BATTERY_LEVEL and vehicle_state.battery_level != -1:
        message.append(f"🔋 {vehicle_state.battery_level:.1f}%")
    elif vehicle_state.battery_level != -1:
        message.append(f"🛢️ {vehicle_state.battery_level:.1f}% {MESSAGES['low_battery']}")
    
    if vehicle_state.est_range > 0:
        if CONFIG["units"] == "Km":
            message.append(f"🛣️ {math.floor(vehicle_state.est_range)} Km")
        else:
            message.append(f"🛣️ {math.floor(vehicle_state.est_range / 1.609)} Miles")
    
    if vehicle_state.state == "charging":
        if vehicle_state.time_to_full_charge == 0 and vehicle_state.charger_power > 0:
            message.append(MESSAGES["charge_ended"])
        else:
            hours, minutes = divmod(vehicle_state.time_to_full_charge, 1)
            minutes = int(minutes * 60)
            message.append(f"⏳ {int(hours)} {pluralize(MESSAGES['hour'], hours)} {minutes} {pluralize(MESSAGES['minute'], minutes)}")
        message.append(f"⚡ {vehicle_state.charge_session_kwh:.2f} kWh Added")
        message.append(f"⚡ {vehicle_state.charger_power:.0f} kW")
        message.append(f"⚡ {vehicle_state.charger_current:.0f} A")
    
    if CONFIG["timestamp_position"] == "bottom":
        message.append(f"\n{timestamp}")
    
    full_message = "\n".join(message)
    send_telegram_message(full_message)

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

if CONFIG["mqtt_broker_username"] and CONFIG["mqtt_broker_password"]:
    client.username_pw_set(CONFIG["mqtt_broker_username"], CONFIG["mqtt_broker_password"])

try:
    client.connect(CONFIG["mqtt_broker_host"], CONFIG["mqtt_broker_port"])
except Exception as e:
    logging.error(f"Failed to connect to MQTT broker: {e}")
    send_telegram_message(MESSAGES["broker_failed"])
    exit(1)

client.loop_forever()
