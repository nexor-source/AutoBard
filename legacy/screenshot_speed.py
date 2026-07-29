# 对比 mss 截屏 100 张 和 pyautogui 截屏 100 张的速度

import time
import mss
import cv2
import numpy as np
import pyautogui

# 定义截图区域
region = (400, 400, 800, 800)

# mss 截屏 100 张
start = time.time()
for i in range(500):
    with mss.mss() as sct:
        monitor = {
            "top": region[1],
            "left": region[0],
            "width": region[2] - region[0],
            "height": region[3] - region[1]
        }
        sct_img = sct.grab(monitor)
        img = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
end = time.time()
print(f"mss 截屏 100 张耗时：{end - start:.4f} seconds")

# pyautogui 截屏 100 张
start = time.time()
for i in range(500):
    img2 = pyautogui.screenshot(region=region)
    img2 = cv2.cvtColor(np.array(img2), cv2.COLOR_RGB2BGR)
end = time.time()
print(f"pyautogui 截屏 100 张耗时：{end - start:.4f} seconds")

"""
结论：
mss爆杀pyautogui, sb掉帧是pyautogui搞的
"""