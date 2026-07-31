import random
import subprocess
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, disconnect
import json
import time
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)
socketio.init_app(app, cors_allowed_origins="*")

# 游戏用参数
clients = {}
# 结构 {'username': {'client_id': 'xxx', 'role': 'xxx'}}
connects = []
players = []
waits = []

startGame = False
smartPlayer = None
honestPlayer = None
playerLimit = 3
selectedWord = None
endState = 0
countDownSecond = 40
countDownEndsAt = None

wordDataBaseDefault = (
    {'word': '模拟词语1',
     'difficulty': 1,
     'hint': '提示/词语/啊',
     'story': '模拟词语是我在做这个游戏的时候用来模拟的词语。',
     'image': 'a_example_1'
     },
    {'word': '模拟词语2',
         'difficulty': 1,
         'hint': '提示/词语/啊',
         'story': '模拟词语是我在做这个游戏的时候用来模拟的词语。',
         'image': 'a_example_2'
         },
    {'word': '模拟词语3',
         'difficulty': 1,
         'hint': '提示/词语/啊',
         'story': '模拟词语是我在做这个游戏的时候用来模拟的词语。',
         'image': 'a_example_3'
         },
    {'word': '模拟词语4',
         'difficulty': 1,
         'hint': '提示/词语/啊',
         'story': '模拟词语是我在做这个游戏的时候用来模拟的词语。',
         'image': 'a_example_4'
         },
)

wordDataBaseFull = None
# read from json file at static/data.json
with open('static/data.json', 'r') as f:
    wordDataBaseFull = json.load(f)

wordDataBase = list(wordDataBaseDefault)
wordDataBaseMode = 'tutor'
selectedWords = []


def reset_game_state(reset_settings=False):
    global smartPlayer, honestPlayer, startGame, selectedWord, endState, wordDataBase, wordDataBaseMode, countDownSecond, countDownEndsAt
    clients.clear()
    connects.clear()
    players.clear()
    waits.clear()
    startGame = False
    smartPlayer = None
    honestPlayer = None
    selectedWord = None
    endState = 0
    countDownEndsAt = None
    selectedWords.clear()
    if reset_settings:
        countDownSecond = 40
        wordDataBase = list(wordDataBaseDefault)
        wordDataBaseMode = 'tutor'


def emit_current_settings(client_id):
    emit('system_message', {
        'type': 'settingsSync',
        'message': None,
        'countdown': countDownSecond,
        'deck': wordDataBaseMode
    }, room=client_id)


def client_id_to_usename(client_id):
    for username in clients:
        if clients[username]['client_id'] == client_id:
            return username
    return False


def current_username():
    return client_id_to_usename(request.sid)


def current_role():
    username = current_username()
    if not username:
        return None
    return clients[username].get('role')


def is_smart_player():
    return current_role() == 'smart'


def reject(message):
    emit('system_message', {'type': None, 'message': message}, room=request.sid)


def pick_word():
    if not wordDataBase:
        return None

    if len(selectedWords) >= len(wordDataBase):
        emit('game_message', {'type': None, 'message': '词库已空，重新开始'}, broadcast=True)
        selectedWords.clear()

    available_words = [word for word in wordDataBase if word not in selectedWords]
    word = random.choice(available_words)
    selectedWords.append(word)
    return word


def emit_role_card(username, word, reconnect=False):
    client_id = clients[username]['client_id']
    if client_id is None:
        return

    role = clients[username]['role']
    if role == 'smart':
        message = '【你是大聪明】：给出一个倒计时信号！'
    elif role == 'honest':
        message = '【你是老实人】：请速记卡片！'
    else:
        message = '【你是瞎掰人】：请准备瞎掰！别忘了假装阅读的样子！'

    payload = {'type': role, 'message': message, 'image': word['image']}
    if reconnect:
        payload['type2'] = 'reconnect'
        payload['remaining'] = max(0, int(countDownEndsAt - time.time())) if countDownEndsAt else None
    emit('game_message', payload, broadcast=False, room=client_id)


def number_players():
    count = 0
    for user in clients:
        if clients[user]['client_id'] is not None:
            count += 1
    return count


def update_online_num():
    emit('system_state', {'type': None,
                          'message': f'{len(players)}/{len(waits)}/{len(connects) - len(waits) - len(players)}'},
         broadcast=True)


def get_git_version():
    try:
        return subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            cwd=app.root_path,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return 'unknown'


def login_client(username, reconnect_token=None):
    client_id = request.sid
    if not isinstance(username, str) or not username.strip():
        emit('system_message', {'type': 'loginError', 'message': '用户名不能为空'}, room=client_id)
        return

    username = username.strip()
    if username.startswith('!!'):
        emit('system_message', {'type': 'loginError', 'message': '用户名格式无效'}, room=client_id)
        return

    if username not in clients:
        clients[username] = {
            'client_id': client_id,
            'role': None,
            'smartCnt': 0,
            'reconnect_token': reconnect_token
        }
        emit('system_message', {'type': None, 'message': f'{username}已加入'}, broadcast=True)
        emit('system_message', {'type': 'success', 'message': username}, room=client_id)
        join(username)
        return

    user = clients[username]
    old_client_id = user['client_id']
    same_browser = (
        reconnect_token
        and user.get('reconnect_token')
        and reconnect_token == user['reconnect_token']
    )

    if old_client_id is None or same_browser:
        user['client_id'] = client_id
        if reconnect_token:
            user['reconnect_token'] = reconnect_token

        if old_client_id and old_client_id != client_id:
            if old_client_id in players:
                players[players.index(old_client_id)] = client_id
            if old_client_id in waits:
                waits[waits.index(old_client_id)] = client_id
            disconnect(old_client_id)

        emit('system_message', {'type': None, 'message': f'{username}已重连'}, broadcast=True)
        emit('system_message', {'type': 'success', 'message': username}, room=client_id)
        reconnect(username)
        return

    emit('system_message', {
        'type': 'loginError',
        'message': f'{username}已被占用，请重新输入'
    }, room=client_id)

@app.route('/')
def index():
    return render_template('index.html', git_version=get_git_version())


@socketio.on('connect')
def handle_connect():
    # print(f'Client connected: {request.sid}')
    connects.append(request.sid)
    update_online_num()

    emit('system_message', {'type': 'handshake', 'message': '请输入一个用户名 \n(如果输入后没有收到 "登陆成功"，请刷新)'}, room=request.sid)
    emit_current_settings(request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    global smartPlayer, honestPlayer, startGame, selectedWord, endState, selectedWords, wordDataBase
    # print(f'Client disconnected: {request.sid}')
    username = client_id_to_usename(request.sid)
    if request.sid in connects:
        connects.remove(request.sid)
    if request.sid in waits:
        waits.remove(request.sid)
    if request.sid in players:
        players.remove(request.sid)
    update_online_num()

    if username:
        clients[username]['client_id'] = None
        emit('system_message', {'type': request.sid, 'message': f'{username}已离开'}, broadcast=True)

    # 如果没人在线 清空所有数据
    if len(connects) == 0:
        reset_game_state()


@socketio.on('login')
def handle_login(data):
    if current_username():
        return
    if not isinstance(data, dict):
        reject('登录信息格式无效')
        return
    login_client(data.get('username'), data.get('token'))


@socketio.on('logout')
def handle_logout():
    username = current_username()
    if not username:
        reject('当前没有登录用户名')
        return
    if startGame:
        reject('游戏进行中不能退出用户名，请先结束本局')
        return

    clients.pop(username, None)
    if request.sid in players:
        players.remove(request.sid)
    if request.sid in waits:
        waits.remove(request.sid)
    emit('system_message', {'type': 'loggedOut', 'message': None}, room=request.sid)
    emit('system_message', {'type': None, 'message': f'{username}已退出用户名'}, broadcast=True)
    update_online_num()


@socketio.on('message_from_client')
def handle_message(message):
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord, endState, selectedWords, wordDataBase, wordDataBaseMode, countDownSecond, countDownEndsAt

    client_id = request.sid
    # print(f'Client ID: {client_id}, Message: {message}')

    # 兼容旧客户端：第一条普通消息仍可作为用户名登录。
    if not client_id_to_usename(client_id):
        login_client(message)
        return

    # 普通消息处理
    else:
        # 特殊指令处理
        if message.startswith('!!'):
            username = current_username()
            if message == '!!start' and not startGame:
                if number_players() < playerLimit:
                    emit('system_message', {'type': None, 'message': '人数不足'}, room=client_id)
                    return
                else:
                    emit('system_message', {'type': None, 'message': '游戏开始'}, broadcast=True)
                    startGame = True
                    start_game()
                    return
            elif message == '!!end':
                if not is_smart_player():
                    reject('只有大聪明可以结束游戏')
                    return
                if startGame and endState == 0:
                    endState = 1
                    countDownEndsAt = None
                    emit('game_message', {'type': 'end', 'message': '游戏结束\n============='}, broadcast=True)
                    return
                elif startGame and endState == 1:
                    endState = 0
                    startGame = False
                    countDownEndsAt = None
                    for user in clients:
                        clients[user]['role'] = None
                    emit('game_message', {'type': 'end2', 'message': None}, broadcast=True)
                    return
            elif message == '!!countdown' and startGame:
                if not is_smart_player():
                    reject('只有大聪明可以发牌开始倒计时')
                    return
                if countDownEndsAt and countDownEndsAt > time.time():
                    reject('倒计时已经开始')
                    return
                countDownEndsAt = time.time() + countDownSecond
                emit('game_message',
                     {'type': 'countdown', 'message': '倒计时马上开始!', 'remaining': countDownSecond},
                     broadcast=True)
                return
            elif message.startswith('!!setCountDown') and not startGame:
                parts = message.split()
                if len(parts) != 2:
                    reject('请输入有效倒计时秒数')
                    return
                try:
                    countDown = int(parts[1])
                except ValueError:
                    reject('倒计时必须是整数')
                    return
                if countDown < 10 or countDown > 600:
                    reject('倒计时必须在 10 到 600 秒之间')
                    return
                countDownSecond = countDown
                emit('system_message', {'type': 'settingCountDown', 
                                        'message': f'倒计时被 {username} 设置为 {countDown} 秒', 
                                        'value': countDown}, broadcast=True)
                return
            elif message == '!!useFull' and not startGame:
                wordDataBase = wordDataBaseFull.copy()
                wordDataBaseMode = 'full'
                selectedWords.clear()
                emit('system_message', {'type': 'useFull',
                                        'message': f'词库已被 {username} 重置为 500全词库'}, broadcast=True)
                return
            elif message == '!!useTutor' and not startGame:
                wordDataBase = list(wordDataBaseDefault)
                wordDataBaseMode = 'tutor'
                selectedWords.clear()
                emit('system_message', {'type': 'useTutor',
                                        'message': f'词库已被 {username} 重置为 教学词库'}, broadcast=True)
                return
            elif message == "!!resetAll":
                if startGame and not is_smart_player():
                    reject('游戏中只有大聪明可以强制初始化')
                    return
                emit('system_message', {'type': 'resetAll', 'message': '所有数据已被重置,请刷新页面后加入'}, broadcast=True)
                for connect in connects.copy():
                    disconnect(connect)
                reset_game_state(reset_settings=True)
                return
            elif message == "!!skip" and startGame:
                if not is_smart_player():
                    reject('只有大聪明可以跳过当前词')
                    return
                # repick word
                word = pick_word()
                if word is None:
                    reject('词库为空，无法选词')
                    return
                selectedWord = word
                countDownEndsAt = None
                
                # resend start message    
                for i in clients:
                    if clients[i]['client_id'] is not None and clients[i]['role'] is not None:
                        emit_role_card(i, word)
                emit('game_message', {'type': 'skip', 'message': '重新选词，身份不变'}, broadcast=True)
                return
            else:
                reject('当前状态下不能执行这个操作')
                return
                

        # 普通消息处理
        else:
            emit('player_message', {'type': client_id, 'username': client_id_to_usename(client_id),
                                    'message': message}, broadcast=True)
            return


def start_game():
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord, players, waits, countDownEndsAt

    # 移除所有没有输入用户名的connection
    to_be_checked = connects.copy()
    for connect in to_be_checked:
        if not client_id_to_usename(connect):
            emit('system_message', {'type': None, 'message': '游戏已开始，由于未输入用户名，已断开连接'}, room=connect)
            disconnect(connect)



    players = [
        info['client_id'] for info in clients.values()
        if info['client_id'] is not None
    ]
    waits = []
    countDownEndsAt = None
    update_online_num()

    # 安排游戏逻辑
    emit('game_message', {'type': None, 'message': '============='}, broadcast=True)

    if startGame:
        
        chosenList = [
            username for username, info in clients.items()
            if info['client_id'] is not None
        ]
        if len(chosenList) < playerLimit:
            startGame = False
            players = []
            emit('system_message', {'type': None, 'message': '人数不足'}, broadcast=True)
            update_online_num()
            return

        min_smart_count = min(clients[i]['smartCnt'] for i in chosenList)
        least_smart_players = [
            i for i in chosenList
            if clients[i]['smartCnt'] == min_smart_count
        ]
        player_1 = random.choice(least_smart_players)
            
        clients[player_1]['smartCnt'] += 1


        player_2 = player_1  # 老实人
        while player_1 == player_2:
            player_2 = random.choice(chosenList)
        
        smartPlayer = player_1
        honestPlayer = player_2
        
        # 这个player是“大聪明” 其他人是“瞎掰人”
        for i in clients:
            if clients[i]['client_id'] is not None:
                if i == player_1:
                    clients[i]['role'] = 'smart'
                elif i == player_2:
                    clients[i]['role'] = 'honest'
                else:
                    clients[i]['role'] = 'liar'

        # 把大聪明的名字发给所有人
        emit('game_message', {'type': None, 'message': f'{player_1}是大聪明!'},
             broadcast=True)

        # 在wordDataBase中随机选择一个词语，把词语发给所有人
        word = pick_word()
        if word is None:
            startGame = False
            players = []
            emit('system_message', {'type': None, 'message': '词库为空，无法开始游戏'}, broadcast=True)
            update_online_num()
            return
        selectedWord = word

        # emit('game_message', {'type': None,
        #                       'message': f'\n词语： {word["word"]}'
        #                                  f'\n难度： {word["difficulty"]}'
        #                                  f'\n提示： {word["hint"]}'}, broadcast=True)

        # 把词语的store发给老实人，把“开编”发送给瞎掰人
        for i in clients:
            if clients[i]['client_id'] is not None and clients[i]['role'] is not None:
                emit_role_card(i, word)

        # print('大聪明是：', player_1)
        # print('老实人是：', player_2)
        # print('词语是：', word['word'], '，提示是：', word['hint'], '，故事是：', word['story'], '，难度是：', word['difficulty'])


def reconnect(userName):
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord
    word = selectedWord
    if startGame and clients[userName]['client_id'] is not None:
        if clients[userName]['role'] is not None:
            # 有 name，有 role (游戏开始后，退出，重连)

            if clients[userName]['client_id'] not in players:
                players.append(clients[userName]['client_id'])
            if clients[userName]['client_id'] in waits:
                waits.remove(clients[userName]['client_id'])
            update_online_num()
            

            emit('game_message', {'type': None,
                                  'message': '游戏已经开始，重新连接成功'},
                 broadcast=False, room=clients[userName]['client_id'])

            emit('game_message', {'type': None, 'message': '============='},
                 broadcast=False, room=clients[userName]['client_id'])

            emit('game_message', {'type': None,
                                  'message': f'{smartPlayer}是大聪明'},
                 broadcast=False, room=clients[userName]['client_id'])

            # emit('game_message', {'type': None,
            #                       'message': f'\n词语： {word["word"]}\n '
            #                                  f'难度： {word["difficulty"]}\n '
            #                                  f'提示： {word["hint"]}'},
            #      broadcast=False, room=clients[userName]['client_id'])

            if word is not None:
                emit_role_card(userName, word, reconnect=True)

        else:
            # 有 name，无 role (游戏开始后，加入，退出，重连)
            join(userName)
    else:
        # 有 name，无 role (游戏开始前，退出，重连)
        join(userName)


def join(userName):
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord
    if startGame and clients[userName]['client_id'] is not None:
        # 无 name，无 role (游戏开始后，加入)
        emit('system_message', {'type': None,
                                'message': '游戏已经开始，请等待本轮游戏结束'},
             broadcast=False, room=clients[userName]['client_id'])

    # 无 name，无 role (游戏开始前，加入/重连)
    if clients[userName]['client_id'] not in waits:
        waits.append(clients[userName]['client_id'])
    if clients[userName]['client_id'] in players:
        players.remove(clients[userName]['client_id'])
    update_online_num()
    


if __name__ == '__main__':
    socketio.run(
        app,
        port=11280,
        allow_unsafe_werkzeug=True,
        debug=True
    )
