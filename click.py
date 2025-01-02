from pynput.mouse import Button, Controller
import keyboard
import time
import threading

# 鼠标控制器
mouse_controller = Controller()

# 状态标识符，表示鼠标是否持续点击
clicking = False

def hold_click():
    """持续按住鼠标左键，增加点击频率"""
    print("开始持续点击鼠标左键...")
    while clicking:
        mouse_controller.click(Button.left, 1)  # 执行鼠标左键点击
        # 减少延迟，增加点击频率
        time.sleep(0.01)  # 每次点击的时间间隔减少到0.01秒
    print("停止持续点击鼠标左键...")

def toggle_click():
    """切换鼠标左键点击状态"""
    global clicking
    if clicking:
        print("关闭鼠标左键持续点击。")
        clicking = False  # 停止点击
    else:
        print("开启鼠标左键持续点击。")
        clicking = True  # 启动点击
        click_thread = threading.Thread(target=hold_click)
        click_thread.daemon = True
        click_thread.start()

def listen_for_key():
    """监听J键的按下"""
    while True:
        if keyboard.is_pressed('j'):  # 检测是否按下J键
            print("J键被按下，切换鼠标左键点击状态...")
            toggle_click()
            time.sleep(0.2)  # 防止重复触发

if __name__ == "__main__":
    print("按 J 键开始/停止鼠标左键点击。")
    listen_for_key()
