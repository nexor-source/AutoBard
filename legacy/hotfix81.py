import cv2
import numpy as np
import mouse
import time
import ctypes
import mss
# import winsound
# pyinstaller --onefile true.py

# 定义常量
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 消除脚本输出的右键信号
played_notes = 0

# 定义全局变量
global mask, pointer

# 读取同路径下的json文件，获取音符的RGB和指针的RGB
import json
with open('config.json', 'r') as f:
    config = json.load(f)
    note_bgr = config['note_bgr']
    pointer_bgr = config['pointer_bgr']
    debug_mode = config['debug_mode']
    note_tolerance = config['note_tolerance']
    pointer_tolerance = config['pointer_tolerance']



# 定义分辨率
RES_BENCHMARK = (2560, 1440)

# 使用 mss 获取屏幕分辨率
def get_screen_resolution_mss():
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 获取主屏幕
        screen_width = monitor["width"]
        screen_height = monitor["height"]
        return screen_width, screen_height

# 获取实际分辨率
RES_NOW = get_screen_resolution_mss()
print("Current resolution: ", RES_NOW)

# 计算比例因子
scale_x = RES_NOW[0] / RES_BENCHMARK[0]
scale_y = RES_NOW[1] / RES_BENCHMARK[1]
print("Scale factor: ", scale_x, scale_y)

def scale(value, axis):
    return int(value * (scale_x if axis == 'x' else scale_y))


def click_right():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.01)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    

def get_note_area():
    # bar = pyautogui.screenshot(region=(1020, 1145, 1540 - 1020, 1176 - 1145))
    # bar = cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)
    with mss.mss() as sct:
        monitor = {
            "top": scale(1145, 'y'),
            "left": scale(1020, 'x'),
            "width": scale(520, 'x'),
            "height": scale(31, 'y')
        }
        bar = np.array(sct.grab(monitor))
    bar = cv2.cvtColor(bar, cv2.COLOR_BGRA2BGR)
    # 将bar 差值为2560 * 1440 的分辨率
    if scale_x != 1 or scale_y != 1:
        bar = cv2.resize(bar, (520, 31), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite('./debug_images/bar.jpg', bar) if debug_mode else None
    # 对(232,178,54)(RGB)进行相似颜色提取轮廓
    # Compute in signed integers before clipping; uint8 arithmetic can wrap in NumPy 2.
    benchmark = np.array([note_bgr], dtype=np.int32)
    delta = note_tolerance
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(benchmark[0] - delta, 0, 255).astype(np.uint8)
    upper = np.clip(benchmark[0] + delta, 0, 255).astype(np.uint8)
    mask = cv2.inRange(bar, lower, upper)
    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    cv2.imwrite('./debug_images/bar_mask.jpg', mask) if debug_mode else None


    # 获取长方形的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # 只保留面具较大的和边特别长的轮廓
    contours = [contour for contour in contours if cv2.contourArea(contour) > 60 and cv2.boundingRect(contour)[2] > 5]

    # 绘制轮廓
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(bar, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.imwrite('./debug_images/bar_masked.jpg', bar) if debug_mode else None


    # 返回轮廓
    return contours

def get_pointer_area():
    global pointer, mask
    with mss.mss() as sct:
        monitor = {
            "top": scale(1094, 'y'),
            "left": scale(1020, 'x'),
            "width": scale(520, 'x'),
            "height": scale(126, 'y')
        }
        pointer = np.array(sct.grab(monitor))
    pointer = cv2.cvtColor(pointer, cv2.COLOR_BGRA2BGR)
    # 将pointer 差值为2560 * 1440 的分辨率
    if scale_x != 1 or scale_y != 1:
        pointer = cv2.resize(pointer, (520, 126), interpolation=cv2.INTER_CUBIC)

    cv2.imwrite('./debug_images/pointer.jpg', pointer) if debug_mode else None

    # 对(243,196,118)(RGB)进行相似颜色提取轮廓
    # Compute in signed integers before clipping; uint8 arithmetic can wrap in NumPy 2.
    benchmark = np.array([pointer_bgr], dtype=np.int32)
    delta = pointer_tolerance
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(benchmark[0] - delta, 0, 255).astype(np.uint8)
    upper = np.clip(benchmark[0] + delta, 0, 255).astype(np.uint8)
    mask = cv2.inRange(pointer, lower, upper)
    # mask 60~72 行像素全部改为黑色
    mask[scale(60, 'y'):scale(72, 'y'), :] = 0

    cv2.imwrite('./debug_images/pointer_mask_original.jpg', mask) if debug_mode else None

    # 取mask的48~85行
    mask = mask[48:85, :]

    # 每一列如果有白色像素超过15个，就将这一列全部变为白色
    for i in range(mask.shape[1]):
        if np.sum(mask[:, i] == 255) > 18:
            mask[:, i] = 255

    cv2.imwrite('./debug_images/pointer_mask.jpg', mask) if debug_mode else None

    # # 获取长方形的轮廓
    # contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # # # 只保留边特别长的轮廓
    # contours = [contour for contour in contours if (cv2.boundingRect(contour)[3] > 30 * scale_y and cv2.boundingRect(contour)[2] > 2 * scale_x) ]    
    # # # 计算mask轮廓内白色像素占比
    # # for contour in contours:
    # #     x, y, w, h = cv2.boundingRect(contour)
    # #     white_pixels = np.sum(mask[y:y+h, x:x+w] == 255)
    # #     total_pixels = w * h
    # #     if white_pixels / total_pixels < 0.75:
    # #         contours.remove(contour)

    # 遍历mask的每一列，如果某一列的左右两列和自己都是白色，则创造一个contour，这个contour代表这全白的三列，并且加入到contours里
    _mask = mask.copy()
    contours = []
    for i in range(1, _mask.shape[1] - 1):
        if np.sum(_mask[:, i - 1] == 255) == np.sum(_mask[:, i] == 255) == _mask.shape[0]:
            contours.append(np.array([[[i - 1, 0]], [[i - 1, _mask.shape[0]]], [[i, _mask.shape[0]]], [[i, 0]]]))
            _mask[:, i-3:i+3] = 0

    # 绘制轮廓
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(pointer, (x, y + 48), (x + w, y + h + 48), (0, 255, 0), 2)
    if len(contours) != 1:
        cv2.imwrite('./debug_images/error_pointer.jpg', pointer) if debug_mode else None
        cv2.imwrite('./debug_images/error_pointer_mask.jpg', mask) if debug_mode else None
        pass

    cv2.imwrite('./debug_images/pointer_masked.jpg', pointer) if debug_mode else None


    # 返回轮廓
    return contours

def play_song():
    print("\nstart auto playing song")
    # 先获取音符区域
    note_contours = get_note_area()
    remaining_notes = 9999999
    print("remaining notes: ", remaining_notes)
    time.sleep(0.1)
    frame = 0
    # 记录开始时间
    start_time = time.time()
    # 无限循环，弹奏所有的剩余音符
    while remaining_notes and frame < 3:
        loop_start_time = time.time()  # 记录循环开始时间
        # 如果弹奏超过6秒直接掐断
        if time.time() - start_time > 6:
            break
        # 获取pointer区域
        pointers = get_pointer_area()
        print("pointers: ", len(pointers))
        if len(pointers) < 1:
            frame += 1
            global mask, pointer
            cv2.imwrite('./debug_images/no_pointer_mask'+str(frame)+'.jpg', mask) if debug_mode else None
            cv2.imwrite('./debug_images/no_pointer_pointer'+str(frame)+'.jpg', pointer) if debug_mode else None
        elif len(pointers) == 1: 
            frame = 0
            remaining_notes = check_and_click(note_contours, pointers)
            print("remaining_notes: ", (remaining_notes))
        else:
            frame = 0
        # 检测间隔时间
        # time.sleep(0.03)
        print(f"Loop duration: {time.time() - loop_start_time:.4f} seconds")  # 输出循环用时
    print("end auto playing song\n")
    



def check_and_click(note_contours, pointers):
    global played_notes
    # 如果pointers数量大于1，报错
    if len(pointers) != 1:
        print('[ERROR] Pointer number is not 1')
        return False

    # 如果pointers里唯一的指针x坐标中心位置在note_contours里某个轮廓的x坐标范围内，说明需要点击
    _pointer = cv2.boundingRect(pointers[0])
    pointer_x = _pointer[0] + _pointer[2] / 2

    # 将note_contours取cv2.boundingRect建立新列表
    note_contours = [cv2.boundingRect(note_contour) for note_contour in note_contours]
    # 将note_contours按x坐标排序
    note_contours = sorted(note_contours, key=lambda x: x[0])
    
    remain_notes = len(note_contours)
    for note in note_contours:
        # 如果pointer在note范围内，点击
        if note[0] < pointer_x < note[0] + note[2]:
            click_right()
            # 输出后停顿0.1s
            time.sleep(0.15)
            print("play note🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵")
            global mask, pointer
            cv2.imwrite('./debug_images/play_time_mask'+str(remain_notes-1)+'.jpg', mask) if debug_mode else None
            cv2.imwrite('./debug_images/play_time_pointer'+str(remain_notes-1)+'.jpg', pointer) if debug_mode else None
            played_notes += 1
            remain_notes -= 1
            return remain_notes
        # pointer已经超过了这个note，剩余音符数减一
        elif pointer_x > note[0] + note[2]:
            remain_notes -= 1
        # 如果pointer在这个note之前，说明pointer也没法到达后面的note，直接返回剩余音符数
        else:
            return remain_notes

    # 如果pointer已经超越了所有NOTE，返回0
    return 0

def on_mouse_event():
    # 用不到0.0001秒的时间忽略弹奏状态所有弹奏的音符
    global played_notes
    if played_notes:
        played_notes -= 1
        return
    # 判断是否为右键按下事件
    print("[[right click!]]")
    global click_times
    click_times.append(time.time())
    # winsound.Beep(1000, 100)  # 频率为1000Hz，持续时间为200毫秒
    # 保留最近的两次点击时间
    if len(click_times) > 2:
        click_times.pop(0)
    # 检查两次点击时间间隔是否小于0.2秒
    if len(click_times) == 2 and click_times[1] - click_times[0] < 0.2:
        play_song()
        pass

    
click_times = []

# 监听右键点击事件
mouse.on_right_click(on_mouse_event)
print("详细说明请见README.md")
print("SYSTEM ONLINE")

# 保持程序运行
while True:
    time.sleep(100)
