# 重新导入必要的库
import cv2
import numpy as np
from matplotlib import pyplot as plt

# 读取图片
image_path = "bar.jpg"
image = cv2.imread(image_path)

# 调整图像的整体亮度
image = cv2.convertScaleAbs(image, alpha=2.8, beta=0)

# 转换为 Lab 颜色空间
lab = cv2.cvtColor(image, cv2.COLOR_BGR2Lab)

# 提取 b 通道（黄色区域在 b 通道的值较高）
l, a, b = cv2.split(lab)

# 直方图均衡化增强对比度
clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
b_enhanced = clahe.apply(b)

# 计算自适应阈值
_, mask = cv2.threshold(b_enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

# 显示原图和处理结果
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
axes[0].imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
axes[0].set_title("原图")

axes[1].imshow(b_enhanced, cmap="gray")
axes[1].set_title("增强的 b 通道")

axes[2].imshow(mask, cmap="gray")
axes[2].set_title("二值化 Mask")

for ax in axes:
    ax.axis("off")

plt.show()
