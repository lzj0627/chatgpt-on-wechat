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
import json



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
        time.sleep(1)
        # 已登录状态 项目手动重启 热重载有一点延迟 再判断一次是否登录
        alive = itchat.instance.alive
        if alive:
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

@app.route('/user_info')
def user_info():
    friends = itchat.instance.get_friends(update=True)
    with open('/home/chatgpt-on-wechat/tmp/friends.json', 'w') as f:
        json.dump(friends, f)
    return jsonify({'status': True})


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
    check_list = rp_backend.split('.')
    is_ip = all(_.isdigit() for _ in check_list)
    if alive:
        js_code = f"""
        function sendRequest() {{
            $.ajax({{
                url: "{backend + ':10000' if is_ip else backend}/logout", 
                type: "POST", 
                dataType: "json", 
                success: function(response) {{
                    if(response.code == 200){{
                    location.reload();
                    }}else {{
                    alert('未知错误');
                }}
            }},
            error: function() {{
                console.log("错误");
            }}
            }}
            );
        }}
        """
    else:
        js_code = f'''
            $(document).ready(function(){{
            setInterval(function(){{
            $.ajax({{
                url: "{backend + ':10000' if is_ip else backend}/status", 
                type: "GET", 
                dataType: "json", 
                success: function(response) {{
                    if(response.alive){{
                    location.reload();
                    }}else {{
                    console.log('还未登录');
                }}
            }},
            error: function() {{
                console.log("错误");
            }}
            }}
            );
            }}, 5000);
        }});
    '''
    return Response(js_code, mimetype='application/javascript')


if __name__ == "__main__":
    app.run('0.0.0.0', 10000)
    
