from pynput import keyboard
import threading
import time
import random

# 定义一个标志位，控制是否持续按下 p 键
is_space_pressed = False

# 模拟按下 p 键
def press_p():
    controller = keyboard.Controller()  # 创建 Controller 实例
    while True:
        if is_space_pressed: 
            # 输出 p 键
            controller.press('p')
            time.sleep(0.001 + random.uniform(-0.0001, 0.0001))
            
            controller.release('p')
            print("按下 p 键")
            time.sleep(0.001 + random.uniform(-0.0001, 0.0001))  # 控制按键输出的频率
        else:
            time.sleep(0.1)  # 避免空循环占用过多 CPU

# 键盘监听器回调函数
def on_press(key):
    global is_space_pressed
    try:
        if key == keyboard.Key.space:
            is_space_pressed = True
    except AttributeError:
        pass

def on_release(key):
    global is_space_pressed
    try:
        if key == keyboard.Key.space:
            is_space_pressed = False
    except AttributeError:
        pass

# 启动按键模拟线程
press_thread = threading.Thread(target=press_p)
press_thread.daemon = True
press_thread.start()

# 启动键盘监听器
with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()