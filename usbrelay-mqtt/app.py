import os, json, time, threading, re, subprocess, logging
from typing import Dict
from fastapi import FastAPI
from paho.mqtt.client import Client as Mqtt

logging.basicConfig(level=logging.INFO)

MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
BASE_TOPIC = os.getenv("BASE_TOPIC", "usbrelay").rstrip("/")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant").rstrip("/")
CLIENT_NAME = os.getenv("CLIENT_NAME", "usbrelay-bridge")
POLL_SECONDS = max(1, int(os.getenv("POLL_SECONDS", "2")))
RETAIN = os.getenv("RETAIN", "false").lower() == "true"
QOS = int(os.getenv("QOS", "0"))

app = FastAPI()
mqtt = Mqtt(client_id=CLIENT_NAME, clean_session=True)
state: Dict[str,int] = {}
relays_list = []
lock = threading.Lock()

def sh(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return p.stdout

def list_relays():
    out = sh(["/usr/local/bin/usbrelay"])
    names = []
    for line in out.strip().splitlines():
        m = re.match(r"([A-Za-z0-9_]+)=([01])", line.strip())
        if m:
            names.append(m.group(1))
    return sorted(set(names))

def read_states():
    out = sh(["/usr/local/bin/usbrelay"])
    cur = {}
    for line in out.strip().splitlines():
        m = re.match(r"([A-Za-z0-9_]+)=([01])", line.strip())
        if m:
            cur[m.group(1)] = int(m.group(2))
    return cur

def publish_state(name, val):
    topic = f"{BASE_TOPIC}/{name}/state"
    logging.info(f"[MQTT] PUBLISH {topic} {val}")
    mqtt.publish(topic, payload=str(val), qos=QOS, retain=RETAIN)

def publish_discovery(name):
    unique_id = f"usbrelay_{name}"
    payload = {
        "name": f"USBRelay {name}",
        "uniq_id": unique_id,
        "cmd_t": f"{BASE_TOPIC}/{name}/set",
        "stat_t": f"{BASE_TOPIC}/{name}/state",
        "pl_on": "1",
        "pl_off": "0",
        "dev": { "ids": [ "usbrelay_device" ], "name": "USB HID Relay", "mf": "HID Relay", "mdl": "usbrelay" }
    }
    topic = f"{DISCOVERY_PREFIX}/switch/usbrelay/{name}/config"
    logging.info(f"[MQTT] DISCOVERY {topic}")
    mqtt.publish(topic, json.dumps(payload), qos=QOS, retain=True)


def on_connect(client, userdata, flags, rc):
    logging.info(f"[MQTT] on_connect rc={rc}")
    # Discovery + subscribe
    for r in relays_list:
        publish_discovery(r)
        sub_t = f"{BASE_TOPIC}/{r}/set"
        logging.info(f"[MQTT] SUBSCRIBE {sub_t}")
        client.subscribe(sub_t, qos=QOS)
    # İlk state yayını
    with lock:
        cur = read_states()
        state.update(cur)
    for k, v in state.items():
        publish_state(k, v)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode().strip()
        logging.info(f"[MQTT] RX {msg.topic} {payload}")
        name = msg.topic.split("/")[-2]  # .../<name>/set
        if payload not in ("0","1"):
            payload = "1" if payload.lower() in ("on","true") else "0"
        sh(["/usr/local/bin/usbrelay", f"{name}={payload}"])
        with lock:
            state[name] = int(payload)
        publish_state(name, payload)
    except Exception as e:
        logging.exception(f"[ERR] on_message failed: {e}")

def poller():
    while True:
        time.sleep(POLL_SECONDS)
        try:
            cur = read_states()
            ups = []
            with lock:
                for k, v in cur.items():
                    if state.get(k) != v:
                        state[k] = v
                        ups.append((k, v))
            for k, v in ups:
                publish_state(k, v)
        except Exception as e:
            logging.exception(f"[ERR] poller: {e}")

@app.on_event("startup")
def startup():
    global relays_list
    mqtt.enable_logger()
    # Röleleri topla
    relays_list = list_relays()
    logging.info(f"[INIT] Relays: {relays_list}")
    # MQTT bağlan
    if MQTT_USER:
        mqtt.username_pw_set(MQTT_USER, MQTT_PASS or None)
    mqtt.on_connect = on_connect
    mqtt.on_message = on_message
    mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    threading.Thread(target=mqtt.loop_forever, daemon=True).start()
    threading.Thread(target=poller, daemon=True).start()

@app.get("/relays")
def api_relays():
    return {"relays": relays_list, "state": state}

@app.post("/announce")
def api_announce():
    for r in relays_list:
        publish_discovery(r)
    with lock:
        cur = read_states()
        state.update(cur)
    for k, v in state.items():
        publish_state(k, v)
    return {"ok": True, "relays": relays_list, "state": state}

