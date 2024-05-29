# encoding:utf-8
import time

from channel import channel_factory
from common import const
from config import load_config, conf
from plugins import *
import threading
from flask import Flask, render_template, jsonify, Response
from lib import itchat
from flask_cors import CORS
import ipaddress

load_config()
RUN_PORT = conf().get('port', 10000)

def start_channel(channel_name: str):
    channel = channel_factory.create_channel(channel_name)
    if channel_name in ["wx", "wxy", "terminal", "wechatmp", "wechatmp_service", "wechatcom_app", "wework",
                        const.FEISHU, const.DINGTALK]:
        PluginManager().load_plugins()

    if conf().get("use_linkai"):
        try:
            from common import linkai_client
            threading.Thread(target=linkai_client.start, args=(channel,)).start()
        except Exception as e:
            pass
    channel.startup()
    while True:
        time.sleep(1)


app = Flask(__name__)
CORS(app, supports_credentials=True)

@app.route('/online')
def online():
    alive = itchat.instance.alive
    if not alive:
        # load config
        load_config()
        threading.Thread(target=start_channel, args=('wx',)).start()
        while not itchat.instance.uuid:
            if itchat.instance.alive:
                return render_template('online.html', img_url=None)
        url = f"https://login.weixin.qq.com/l/{itchat.instance.uuid}"
        img_url = f"https://api.pwmqr.com/qrcode/create/?url={url}"
        return render_template('online.html', img_url=img_url)
    return render_template('online.html', img_url=None)

@app.route('/status')
def status():
    alive= itchat.instance.alive
    data = {'alive': alive}
    return jsonify(data)

@app.route('/friends')
def friends():
    friends = itchat.instance.get_friends(update=True)
    return jsonify(friends)


@app.route('/logout', methods=['POST'])
def logout():
    try:
        itchat.instance.logout()
        data = {'code': 200, 'msg': '已退出登录'}
    except Exception as e:
        data = {'code': 400, 'msg': '未知错误'}
    return jsonify(data)

@app.route('/index_script.js')
def online_js():
    alive = itchat.instance.alive
    backend = conf().get('backend', '')
    rp_backend = backend.replace('http://', '').replace('https://', '')
    try:
        ipaddress.IPv4Address(rp_backend)
        is_ip = True
    except Exception as e:
        is_ip = False
    backend_url = f'http://{backend}:{str(RUN_PORT)}' if is_ip else backend
    if alive:
        js_code = f"""
        function sendRequest() {{
            $.ajax({{
                url: "{backend_url}/logout", 
                type: "POST", 
                dataType: "json", 
                success: function(response) {{
                    if(response.code == 200){{
                        location.reload();
                        }}
                    else {{
                        alert('未知错误');
                    }}
                }},
                error: function() {{
                    console.log("错误");
                }}
            }});
        }}
        """
    else:
        js_code = f'''
            $(document).ready(function(){{
                setInterval(function(){{
                    $.ajax({{
                        url: "{backend_url}/status", 
                        type: "GET", 
                        dataType: "json", 
                        success: function(response) {{
                            if(response.alive){{
                                location.reload();
                                }}
                            else {{
                                console.log('还未登录');
                            }}
                        }},
                        error: function() {{
                            console.log("错误");
                        }}
                    }});
                }}, 1000);
            }});
            setTimeout(function(){{
                location.reload();
                }}, 300000)
    '''
    return Response(js_code, mimetype='application/javascript')


if __name__ == "__main__":
    app.run('0.0.0.0', RUN_PORT)
    
