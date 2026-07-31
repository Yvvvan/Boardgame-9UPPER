import random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, disconnect
import json
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
selectedWords = []

def client_id_to_usename(client_id):
    for username in clients:
        if clients[username]['client_id'] == client_id:
            return username
    return False


def number_players():
    count = 0
    for user in clients:
        if clients[user]['client_id'] is not None:
            count += 1
    return count


def update_online_num():
    emit('system_state', {'type': None,
                          'message': f'P/W/C:{len(players)}/{len(waits)}/{len(connects) - len(waits) - len(players)}'},
         broadcast=True)

@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    # print(f'Client connected: {request.sid}')
    connects.append(request.sid)
    update_online_num()

    emit('system_message', {'type': 'handshake', 'message': '请输入一个用户名 \n(如果输入后没有收到 "登陆成功"，请刷新)'}, room=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    global smartPlayer, honestPlayer, startGame, selectedWord, endState, selectedWords
    # print(f'Client disconnected: {request.sid}')
    username = client_id_to_usename(request.sid)
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
        clients.clear()
        players.clear()
        waits.clear()
        startGame = False
        smartPlayer = None
        honestPlayer = None
        selectedWord = None
        endState = 0
        selectedWords.clear()
        wordDataBase = list(wordDataBaseDefault)


@socketio.on('message_from_client')
def handle_message(message):
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord, endState, selectedWords, wordDataBase

    client_id = request.sid
    # print(f'Client ID: {client_id}, Message: {message}')

    # 用户名处理， 第一条消息 (=当client_id 没有被记录时)
    if not client_id_to_usename(client_id):
        userName = message
        if userName.startswith('!!'):
            emit('system_message', {'type': None, 'message': None}, room=client_id)
            return
        if userName not in clients:
            clients[userName] = {'client_id': client_id, 'role': None, 'smartCnt':0}
            emit('system_message', {'type': None, 'message': f'{userName}已加入'}, broadcast=True)
            emit('system_message', {'type': "success", 'message': userName}, room=client_id)
            join(userName)

        elif userName in clients and clients[userName]['client_id'] is None:
            clients[userName]['client_id'] = client_id
            emit('system_message', {'type': None, 'message': f'{userName}已重连'}, broadcast=True)
            emit('system_message', {'type': "success", 'message': userName}, room=client_id)
            reconnect(userName)

        elif userName in clients and clients[userName]['client_id'] is not None:
            emit('system_message', {'type': None, 'message': f'{userName}已被占用，请重新输入'}, room=client_id)
            return

        else:
            emit('system_message', {'type': None, 'message': '未知错误'}, room=client_id)
            return

    # 普通消息处理
    else:
        # 特殊指令处理
        if message.startswith('!!'):
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
                if startGame and endState == 0:
                    endState = 1
                    emit('game_message', {'type': 'end', 'message': '游戏结束\n============='}, broadcast=True)
                    return
                elif startGame and endState == 1:
                    endState = 0
                    startGame = False
                    for user in clients:
                        clients[user]['role'] = None
                    emit('game_message', {'type': 'end2', 'message': None}, broadcast=True)
                    return
            elif message == '!!countdown' and startGame:
                emit('game_message', {'type': 'countdown', 'message': '倒计时马上开始!'}, broadcast=True)
                return
            elif '!!setCountDown' in message and not startGame:
                countDown = message.split(' ')[1]
                emit('system_message', {'type': 'settingCountDown', 
                                        'message': f'倒计时被 {client_id_to_usename(client_id)} 设置为 {countDown} 秒', 
                                        'value': int(countDown)}, broadcast=True)
                return
            elif message == '!!useFull' and not startGame:
                wordDataBase = wordDataBaseFull.copy()
                emit('system_message', {'type': 'useFull',
                                        'message': f'词库已被 {client_id_to_usename(client_id)} 重置为 500全词库'}, broadcast=True)
                return
            elif message == '!!useTutor' and not startGame:
                wordDataBase = list(wordDataBaseDefault)
                emit('system_message', {'type': 'useTutor',
                                        'message': f'词库已被 {client_id_to_usename(client_id)} 重置为 教学词库'}, broadcast=True)
                return
            elif message == "!!resetAll":
                emit('system_message', {'type': 'resetAll', 'message': '所有数据已被重置,请刷新页面后加入'}, broadcast=True)
                for connect in connects:
                    disconnect(connect)
                connects.clear()
                clients.clear()
                players.clear()
                waits.clear()
                startGame = False
                smartPlayer = None
                honestPlayer = None
                selectedWord = None
                endState = 0
                selectedWords.clear()
                wordDataBase = list(wordDataBaseDefault)
                return
            elif message == "!!skip" and startGame:
                # repick word
                word = random.choice(wordDataBase)
                while word in selectedWords:
                    word = random.choice(wordDataBase)
                    if len(selectedWords) == len(wordDataBase):
                        emit('game_message', {'type': None, 'message': '词库已空，重新开始'}, broadcast=True)
                        selectedWords.clear()
                selectedWords.append(word)
                selectedWord = word
                
                # resend start message    
                for i in clients:
                    if clients[i]['client_id'] is not None:
                        if i == smartPlayer:
                            message = '【你是大聪明】：给出一个倒计时信号！'
                            msgtype = 'smart'
                        elif i == honestPlayer:
                            message = '【你是老实人】：请速记卡片！'
                            msgtype = 'honest'
                        else:
                            message = '【你是瞎掰人】：请准备瞎掰！别忘了假装阅读的样子！'
                            msgtype = 'liar'
                    emit('game_message', {'type': msgtype,
                                        'message': message, 'image': word['image']},
                        broadcast=False, room=clients[i]['client_id'])
                emit('game_message', {'type': 'skip', 'message': '重新选词，身份不变'}, broadcast=True)
                

        # 普通消息处理
        else:
            emit('player_message', {'type': client_id, 'username': client_id_to_usename(client_id),
                                    'message': message}, broadcast=True)
            return


def start_game():
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord, players, waits

    # 移除所有没有输入用户名的connection
    to_be_checked = connects.copy()
    for connect in to_be_checked:
        if not client_id_to_usename(connect):
            emit('system_message', {'type': None, 'message': '游戏已开始，由于未输入用户名，已断开连接'}, room=connect)
            disconnect(connect)



    players = connects.copy()
    waits = []
    update_online_num()

    # 安排游戏逻辑
    emit('game_message', {'type': None, 'message': '============='}, broadcast=True)

    if startGame:
        
        chosenList = []
        for i in clients:
            if clients[i]['client_id'] is not None:
                chosenList.append(i)
        # 按smartCnt从小到大排序
        chosenList.sort(key=lambda x: clients[x]['smartCnt'])
        # 轮流选择 不是上一次的smartPlayer 就行
        for i in chosenList:
            if i != smartPlayer:
                player_1 = i
                break
            
        clients[player_1]['smartCnt'] += 1


        player_2 = player_1  # 老实人
        while player_1 == player_2 or clients[player_2]['client_id'] is None:
            player_2 = random.choice(list(clients.keys()))
        
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
        word = random.choice(wordDataBase)
        while word in selectedWords:
            word = random.choice(wordDataBase)
            if len(selectedWords) == len(wordDataBase):
                emit('game_message', {'type': None, 'message': '词库已空，重新开始'}, broadcast=True)
                selectedWords.clear()
        selectedWords.append(word)
        selectedWord = word

        # emit('game_message', {'type': None,
        #                       'message': f'\n词语： {word["word"]}'
        #                                  f'\n难度： {word["difficulty"]}'
        #                                  f'\n提示： {word["hint"]}'}, broadcast=True)

        # 把词语的store发给老实人，把“开编”发送给瞎掰人
        for i in clients:
            if clients[i]['client_id'] is not None:
                if i == player_1:
                    message = '【你是大聪明】：给出一个倒计时信号！'
                    msgtype = 'smart'
                elif i == player_2:
                    message = '【你是老实人】：请速记卡片！'
                    msgtype = 'honest'
                else:
                    message = '【你是瞎掰人】：请准备瞎掰！别忘了假装阅读的样子！'
                    msgtype = 'liar'
            emit('game_message', {'type': msgtype,
                                  'message': message, 'image': word['image']},
                 broadcast=False, room=clients[i]['client_id'])

        # print('大聪明是：', player_1)
        # print('老实人是：', player_2)
        # print('词语是：', word['word'], '，提示是：', word['hint'], '，故事是：', word['story'], '，难度是：', word['difficulty'])


def reconnect(userName):
    global smartPlayer, honestPlayer, startGame, playerLimit, selectedWord
    word = selectedWord
    if startGame and clients[userName]['client_id'] is not None:
        if clients[userName]['role'] is not None:
            # 有 name，有 role (游戏开始后，退出，重连)

            players.append(clients[userName]['client_id'])
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

            if clients[userName]['role'] == 'liar':
                message = '【你是瞎掰人】：请准备瞎掰！别忘了假装阅读的样子！'
                msgtype = 'liar'
            elif clients[userName]['role'] == 'honest':
                message = '【你是老实人】：请速记卡片！'
                msgtype = 'honest'
            else:
                message = '【你是大聪明】：给出一个倒计时信号！'
                msgtype = 'smart'
            emit('game_message', {'type': msgtype, 'type2' : 'reconnect',
                                  'message': message, 'image': word['image']},
                 broadcast=False, room=clients[userName]['client_id'])

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
    waits.append(clients[userName]['client_id'])
    update_online_num()
    


if __name__ == '__main__':
    socketio.run(app, port=15672, allow_unsafe_werkzeug=True,debug=False)
