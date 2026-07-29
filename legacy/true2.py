import cv2
import numpy as np
import mouse
import pyautogui
import time
import ctypes
import random
import winsound

# 定义常量
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 定义鼠标事件函数
def click_right():
    # 发出bi的声音
    

    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(random.random() * 0.01)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    winsound.Beep(1000, 200)  # 频率1000Hz，持续时间200ms

def get_note_area(show = False):
    bar = pyautogui.screenshot(region=(1020, 1145, 1540 - 1020, 1176 - 1145))
    bar = cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)
    cv2.imwrite('bar.jpg', bar)

    # 对(232,178,54)(RGB)进行相似颜色提取轮廓
    benchmark = np.uint8([[54, 178, 232]])
    delta = 44
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(np.array([benchmark[0][0] - delta, benchmark[0][1] - delta, benchmark[0][2] - delta]), 0, 255)
    upper = np.clip(np.array([benchmark[0][0] + delta, benchmark[0][1] + delta, benchmark[0][2] + delta]), 0, 255)
    mask = cv2.inRange(bar, lower, upper)
    cv2.imwrite('bar_mask.jpg', mask)

    # 可视化bar
    if show:
        cv2.imshow('bar', bar)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    # 获取长方形的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # 只保留面具较大的和边特别长的轮廓
    contours = [contour for contour in contours if cv2.contourArea(contour) > 70]
    if show:
        print(len(contours))
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            print(x, x + w)

    # 绘制轮廓
    # if show:
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(bar, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.imwrite('bar_masked.jpg', bar)

        # cv2.imshow('bar', bar)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()

    # 返回轮廓
    return contours

def get_pointer_area(show = False):
    pointer = pyautogui.screenshot(region=(1020, 1094, 1540 - 1020, 1220 - 1094))
    pointer = cv2.cvtColor(np.array(pointer), cv2.COLOR_RGB2BGR)

    cv2.imwrite('pointer.jpg', pointer)

    # 对(243,196,118)(RGB)进行相似颜色提取轮廓
    benchmark = np.uint8([[118, 196, 243]])
    delta = 50
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(np.array([benchmark[0][0] - delta, benchmark[0][1] - delta, benchmark[0][2] - delta]), 0, 255)
    upper = np.clip(np.array([benchmark[0][0] + delta, benchmark[0][1] + delta, benchmark[0][2] + delta]), 0, 255)
    mask = cv2.inRange(pointer, lower, upper)
    # 指针的mask中所有白色像素向外膨胀一圈
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    cv2.imwrite('pointer_mask.jpg', mask)

    # 可视化pointer
    if show:
        cv2.imshow('mask', mask)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    # 获取长方形的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # # 只保留边特别长的轮廓
    contours = [contour for contour in contours if cv2.boundingRect(contour)[3] > 60]

    if show:
        print(len(contours))
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            print(x, x + w)

    # 绘制轮廓
    # if show:
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(pointer, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.imwrite('pointer_masked.jpg', pointer)
        # cv2.imshow('pointer', pointer)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()

    # 返回轮廓
    return contours


def play_song():
    print("start auto playing song")
    # 先获取音符区域
    note_contours = get_note_area()
    remaining_notes = len(note_contours)
    print("remaining notes: ", remaining_notes)
    time.sleep(0.1)

    # 记录开始时间
    start_time = time.time()
    
    # 无限循环，弹奏所有的剩余音符
    while remaining_notes:
        # 如果弹奏超过6秒直接掐断
        if time.time() - start_time > 6:
            break
        # 获取pointer区域
        pointers = get_pointer_area()
        get_note_area()
        print("pointers: ", len(pointers))
        if len(pointers) != 1:
            break
        tok = check_and_click(note_contours, pointers)
        if tok:
            remaining_notes -= 1
            print("remaining notes: ", remaining_notes, " tok: ", tok)
            if tok == -1:
                break
            else:
                time.sleep(max(tok * 0.0047 - 0.1, 0.04))

    print("end auto playing song")


def check_and_click(note_contours, pointers):
    # 如果pointers数量大于1，报错
    if len(pointers) != 1:
        print('[ERROR] Pointer number is not 1')
        return False

    # 如果pointers里唯一的指针x坐标中心位置在note_contours里某个轮廓的x坐标范围内，说明需要点击
    pointer = cv2.boundingRect(pointers[0])
    pointer_x = pointer[0] + pointer[2] / 2

    clicked = False
    # 将note_contours按照x坐标排序
    note_contours = sorted(note_contours, key=lambda x: cv2.boundingRect(x)[0])
    for note_contour in note_contours:
        note = cv2.boundingRect(note_contour)
        # 点击完成，返回与下个音符的距离
        if clicked:
            return note[0] - 2 - pointer_x
        # 如果在某个音符里面
        if note[0] - 2 < pointer_x < note[0] + note[2]:
            click_right()
            clicked = True
            print("play note")
    # 点击完成，由于没有下个音符所以直接返回
    if clicked:
        return -1
    return False

# 右键点击两次触发自动弹奏
def on_right_click():
    global click_times
    click_times.append(time.time())
    # 保留最近的两次点击时间
    if len(click_times) > 2:
        click_times.pop(0)
    # 检查两次点击时间间隔是否小于0.2秒
    if len(click_times) == 2 and click_times[1] - click_times[0] < 0.2:
        play_song()

click_times = []

# 监听右键点击事件
mouse.on_right_click(on_right_click)

# 保持程序运行
while True:
    time.sleep(0.2)