from pynput import mouse

def on_click(x, y, button, pressed):
    if pressed:
        if button == mouse.Button.x1:  # 侧键1
            print("检测到鼠标侧键1按下，执行脚本")
            execute_script()
        elif button == mouse.Button.x2:  # 侧键2
            print("检测到鼠标侧键2按下，执行脚本")
            execute_script()

def start_mouse_listener():
    # 启动鼠标监听器
    print("启动鼠标监听器，按下鼠标侧键1或侧键2以执行脚本")
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()

def execute_script():
    print("脚本执行中...")

# 调用函数来启动监听
start_mouse_listener()
