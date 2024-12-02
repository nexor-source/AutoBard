import cv2
import numpy as np
import mouse
import time
import ctypes
import mss
# import winsound


# 定义常量
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 消除脚本输出的右键信号
played_notes = 0

# 定义分辨率
my_res = (2560, 1440)
cal_res = (1920, 1080)

def click_right():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.01)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    

def get_note_area():
    # bar = pyautogui.screenshot(region=(1020, 1145, 1540 - 1020, 1176 - 1145))
    # bar = cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)
    with mss.mss() as sct:
        monitor = {"top": 1145, "left": 1020, "width": 520, "height": 31}
        bar = np.array(sct.grab(monitor))
    bar = cv2.cvtColor(bar, cv2.COLOR_BGRA2BGR)
    # cv2.imwrite('bar.jpg', bar)
    # 对(232,178,54)(RGB)进行相似颜色提取轮廓
    benchmark = np.uint8([[54, 178, 232]])
    delta = 44
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(np.array([benchmark[0][0] - delta, benchmark[0][1] - delta, benchmark[0][2] - delta]), 0, 255)
    upper = np.clip(np.array([benchmark[0][0] + delta, benchmark[0][1] + delta, benchmark[0][2] + delta]), 0, 255)
    mask = cv2.inRange(bar, lower, upper)
    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    # cv2.imwrite('bar_mask.jpg', mask)


    # 获取长方形的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # 只保留面具较大的和边特别长的轮廓
    contours = [contour for contour in contours if cv2.contourArea(contour) > 60 and cv2.boundingRect(contour)[2] > 5]

    # 绘制轮廓
    # for contour in contours:
    #     x, y, w, h = cv2.boundingRect(contour)
    #     cv2.rectangle(bar, (x, y), (x + w, y + h), (0, 255, 0), 2)
    # cv2.imwrite('bar_masked.jpg', bar)


    # 返回轮廓
    return contours

def get_pointer_area():
    # pointer = pyautogui.screenshot(region=(1020, 1094, 1540 - 1020, 1220 - 1094))
    # pointer = cv2.cvtColor(np.array(pointer), cv2.COLOR_RGB2BGR)
    with mss.mss() as sct:
        monitor = {"top": 1094, "left": 1020, "width": 520, "height": 126}
        pointer = np.array(sct.grab(monitor))
    pointer = cv2.cvtColor(pointer, cv2.COLOR_BGRA2BGR)

    # cv2.imwrite('pointer.jpg', pointer)

    # 对(243,196,118)(RGB)进行相似颜色提取轮廓
    benchmark = np.uint8([[118, 196, 243]])
    delta = 50
    # 确保 lower 和 upper 的值在 0 到 255 之间
    lower = np.clip(np.array([benchmark[0][0] - delta, benchmark[0][1] - delta, benchmark[0][2] - delta]), 0, 255)
    upper = np.clip(np.array([benchmark[0][0] + delta, benchmark[0][1] + delta, benchmark[0][2] + delta]), 0, 255)
    mask = cv2.inRange(pointer, lower, upper)
    # mask 60~72 行像素全部改为黑色
    mask[60:72, :] = 0

    # cv2.imwrite('pointer_mask_original.jpg', mask)

    # # 使用形态学操作去除小的白色噪声
    # kernel = np.ones((3, 3), np.uint8)
    # mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    # 每一列如果有白色像素超过10个，就将这一列全部变为白色
    for i in range(mask.shape[1]):
        if np.sum(mask[:, i] == 255) > 40:
            mask[:, i] = 255

    # cv2.imwrite('pointer_mask.jpg', mask)

    # 获取长方形的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # # 只保留边特别长的轮廓
    contours = [contour for contour in contours if cv2.boundingRect(contour)[3] > 60 and cv2.boundingRect(contour)[2] > 3]

    # 绘制轮廓
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(pointer, (x, y), (x + w, y + h), (0, 255, 0), 2)
    # cv2.imwrite('pointer_masked.jpg', pointer)


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
    while remaining_notes and frame < 2:
        loop_start_time = time.time()  # 记录循环开始时间
        # 如果弹奏超过6秒直接掐断
        if time.time() - start_time > 6:
            break
        # 获取pointer区域
        pointers = get_pointer_area()
        print("pointers: ", len(pointers))
        if len(pointers) != 1:
            frame += 1
        else: 
            frame = 0
            remaining_notes = check_and_click(note_contours, pointers)
            print("remaining_notes: ", (remaining_notes))
        # 检测间隔时间
        time.sleep(0.03)
        print(f"Loop duration: {time.time() - loop_start_time:.4f} seconds")  # 输出循环用时
    print("end auto playing song\n")
    



def check_and_click(note_contours, pointers):
    global played_notes
    # 如果pointers数量大于1，报错
    if len(pointers) != 1:
        print('[ERROR] Pointer number is not 1')
        return False

    # 如果pointers里唯一的指针x坐标中心位置在note_contours里某个轮廓的x坐标范围内，说明需要点击
    pointer = cv2.boundingRect(pointers[0])
    pointer_x = pointer[0] + pointer[2] / 2

    # 将note_contours取cv2.boundingRect建立新列表
    note_contours = [cv2.boundingRect(note_contour) for note_contour in note_contours]
    # 将note_contours按x坐标排序
    note_contours = sorted(note_contours, key=lambda x: x[0])
    
    remain_notes = len(note_contours)
    for note in note_contours:
        # 如果pointer在note范围内，点击
        if note[0] - 4 < pointer_x < note[0] + note[2]:
            click_right()
            # 输出后停顿0.1s
            time.sleep(0.1)
            print("play note🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵🎵")
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

# 保持程序运行
while True:
    time.sleep(100)