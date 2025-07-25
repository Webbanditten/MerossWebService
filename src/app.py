from flask import Flask, render_template
import socket

import asyncio
import os
from flask import jsonify
from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager

# For garage opener
from meross_iot.controller.mixins.garage import GarageOpenerMixin
import threading

app = Flask(__name__)


@app.route("/")
def index():
    try:
        host_name = socket.gethostname()
        host_ip = socket.gethostbyname(host_name)
        return render_template("index.html", hostname=host_name, ip=host_ip)
    except:
        return render_template("error.html")



# Async helper for device listing
async def get_meross_devices():
    EMAIL = os.environ.get('MEROSS_EMAIL') or "YOUR_MEROSS_CLOUD_EMAIL"
    PASSWORD = os.environ.get('MEROSS_PASSWORD') or "YOUR_MEROSS_CLOUD_PASSWORD"
    http_api_client = await MerossHttpClient.async_from_user_password(email=EMAIL, password=PASSWORD, api_base_url="https://iot.meross.com")
    manager = MerossManager(http_client=http_api_client)
    await manager.async_init()
    await manager.async_device_discovery()
    meross_devices = manager.find_devices()
    devices = []
    for dev in meross_devices:
        devices.append({
            'name': dev.name,
            'type': dev.type,
            'online_status': str(dev.online_status)
        })
    manager.close()
    await http_api_client.async_logout()
    return devices


# --- Garage opener state ---
garage_action_lock = threading.Lock()
garage_action_state = {
    'last_action': None,  # 'open', 'close', or None
    'in_progress': False
}

async def garage_action(action):
    EMAIL = os.environ.get('MEROSS_EMAIL') or "YOUR_MEROSS_CLOUD_EMAIL"
    PASSWORD = os.environ.get('MEROSS_PASSWORD') or "YOUR_MEROSS_CLOUD_PASSWORD"
    http_api_client = await MerossHttpClient.async_from_user_password(email=EMAIL, password=PASSWORD, api_base_url="https://iot.meross.com")
    manager = MerossManager(http_client=http_api_client)
    await manager.async_init()
    await manager.async_device_discovery()
    openers = manager.find_devices(device_class=GarageOpenerMixin, device_type="msg100")
    if not openers:
        manager.close()
        await http_api_client.async_logout()
        return {'error': 'No garage opener found.'}
    dev = openers[0]
    await dev.async_update()
    open_status = dev.get_is_open()
    result = {}
    if action == 'open':
        if open_status:
            result['status'] = 'already open'
        else:
            await dev.async_open(channel=0)
            result['status'] = 'opening'
    elif action == 'close':
        if not open_status:
            result['status'] = 'already closed'
        else:
            await dev.async_close(channel=0)
            result['status'] = 'closing'
    else:
        result['error'] = 'Invalid action.'
    manager.close()
    await http_api_client.async_logout()
    return result


def run_garage_action(action):
    with garage_action_lock:
        if garage_action_state['in_progress'] and garage_action_state['last_action'] == action:
            # If same action is in progress, treat as cancel/stop
            garage_action_state['in_progress'] = False
            return {'status': f'{action} stopped'}
        garage_action_state['in_progress'] = True
        garage_action_state['last_action'] = action

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(garage_action(action))
    except Exception as e:
        result = {'error': str(e)}
    finally:
        loop.close()
        with garage_action_lock:
            garage_action_state['in_progress'] = False
    return result


# Endpoint to get garage door status
@app.route("/garage/status", methods=["GET"])
def garage_status():
    async def get_status():
        EMAIL = os.environ.get('MEROSS_EMAIL') or "YOUR_MEROSS_CLOUD_EMAIL"
        PASSWORD = os.environ.get('MEROSS_PASSWORD') or "YOUR_MEROSS_CLOUD_PASSWORD"
        http_api_client = await MerossHttpClient.async_from_user_password(email=EMAIL, password=PASSWORD, api_base_url="https://iot.meross.com")
        manager = MerossManager(http_client=http_api_client)
        await manager.async_init()
        await manager.async_device_discovery()
        openers = manager.find_devices(device_class=GarageOpenerMixin, device_type="msg100")
        if not openers:
            manager.close()
            await http_api_client.async_logout()
            return {'error': 'No garage opener found.'}, 404
        dev = openers[0]
        await dev.async_update()
        open_status = dev.get_is_open()
        manager.close()
        await http_api_client.async_logout()
        return {'open': bool(open_status)}, 200

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        status, code = loop.run_until_complete(get_status())
        return jsonify(status), code
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        loop.close()


@app.route("/garage/open", methods=["POST", "GET"])
def garage_open():
    result = run_garage_action('open')
    if 'error' in result:
        if 'No garage opener found' in result['error']:
            return jsonify(result), 404
        return jsonify(result), 500
    if 'status' in result and result['status'] == 'already open':
        return jsonify(result), 200
    if 'status' in result and result['status'] == 'opening':
        return jsonify(result), 200
    if 'status' in result and result['status'].endswith('stopped'):
        return jsonify(result), 200
    return jsonify(result), 400

@app.route("/garage/close", methods=["POST", "GET"])
def garage_close():
    result = run_garage_action('close')
    if 'error' in result:
        if 'No garage opener found' in result['error']:
            return jsonify(result), 404
        return jsonify(result), 500
    if 'status' in result and result['status'] == 'already closed':
        return jsonify(result), 200
    if 'status' in result and result['status'] == 'closing':
        return jsonify(result), 200
    if 'status' in result and result['status'].endswith('stopped'):
        return jsonify(result), 200
    return jsonify(result), 400


@app.route("/devices")
def list_devices():
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        devices = loop.run_until_complete(get_meross_devices())
        # You can render a template or return JSON. Here, we return JSON for simplicity.
        return jsonify({'devices': devices})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        loop.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
