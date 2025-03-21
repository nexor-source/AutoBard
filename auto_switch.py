from pynput import keyboard, mouse
import time
import threading

# 获取屏幕尺寸
screen_width = 1920
screen_height = 1080

# 计算目标位置
start_x = int(960 / 1920 * screen_width)
start_y = int(160 / 1080 * screen_height)
end_x = int(624 / 1920 * screen_width)
end_y = int(160 / 1080 * screen_height)

# 创建鼠标控制器
mouse_controller = mouse.Controller()

def smooth_drag(start_x, start_y, end_x, end_y, steps=14, delay=0.01):
    # 计算每一步的移动距离
    step_x = (end_x - start_x) / steps
    step_y = (end_y - start_y) / steps

    # 按下鼠标左键
    mouse_controller.press(mouse.Button.left)
    print(f"按下鼠标左键并开始拖动")

    # 分步移动鼠标
    for i in range(steps):
        new_x = start_x + step_x * i
        new_y = start_y + step_y * i
        mouse_controller.position = (new_x, new_y)
        time.sleep(delay)

    # 移动到最终位置
    mouse_controller.position = (end_x, end_y)
    print(f"拖动到目标位置 ({end_x}, {end_y})")

    # 释放鼠标左键
    mouse_controller.release(mouse.Button.left)
    print("释放鼠标左键")

def execute_script(delay = 0.02):
    print("按下 Tab 键")
    keyboard_controller.press(keyboard.Key.tab)
    time.sleep(delay)
    keyboard_controller.release(keyboard.Key.tab)
    time.sleep(delay)

    print(f"移动鼠标到起始位置 ({start_x}, {start_y})")
    mouse_controller.position = (start_x, start_y)
    time.sleep(delay)

    smooth_drag(start_x, start_y, end_x, end_y)

    print("再次按下 Tab 键")
    keyboard_controller.press(keyboard.Key.tab)
    time.sleep(delay)
    keyboard_controller.release(keyboard.Key.tab)
    time.sleep(delay)

def on_click(x, y, button, pressed):
    if pressed:
        if button == mouse.Button.x2:  # 侧键2
            print("检测到鼠标侧键2按下，执行脚本")
            execute_script()

def start_mouse_listener():
    # 启动鼠标监听器
    print("启动鼠标监听器，按下鼠标侧键1或侧键2以执行脚本")
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()

# 创建键盘控制器
keyboard_controller = keyboard.Controller()

# 在单独的线程中启动监听器
listener_thread = threading.Thread(target=start_mouse_listener)
listener_thread.start()