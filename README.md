# 自动弹奏诗人脚本

## 使用方法

**☆☆☆Release中可以直接下载打包好的.exe文件进行检测音符自动弹奏☆☆☆**

打开exe后出现黑色命令框代表程序已启动，**连续右键两下**即可触发检测

例：在有**超凡演奏**天赋的情况下，选取好乐曲后第一下右键正常开始弹奏，第二下右键跳过第一个音符，同时触发检测。
小提示：在演奏过程中手动跳音符可能会导致意想不到的后果，如果弹奏6个音符以上的乐曲稳定解是跳过第一个和最后一个音符。后续版本会尝试解决该问题



## 基本需求

- **至少60FPS，最好120FPS或者更高**，检测的就会更准确
- 代码逻辑使用近似颜色检测，并且使用的是截屏。颜色是基于原生游戏下 3.0 亮度来检测，**滤镜或其他情况需要手动调整检测的RGB值**
- 开发环境原生分辨率$2560\times1440$，测试过$1920\times1080$分辨率，但是**非$16:9$比例的分辨率非常有可能会导致检测失效**
- 由于检测的触发方式（连续右键两下），天赋需要**超凡演奏**



## 进阶

### 手动修改检测的RGB值

首先对游戏中演奏画面进行截图，然后使用画图吸管之类的工具获取**音符中心颜色**与**指针中心颜色**，打开config.json文件，找到note_bgr和pointer_bgr，将你获取的RGB通道数值进行更新（注意config中的数字是BGR的顺序，如果你获取RGB则需要反过来）

![tutorial]([.\debug_images\tutorial.png](https://github.com/nexor-source/AutoBard/blob/main/debug_images/tutorial.png))

### 调试模式 与 检测容差的调整

打开config.json，将 `"debug_mode": false,` 改为 `"debug_mode": true,`打开调试模式，在调试模式下会输出检测时获取的图片以及处理得到的结果，保存在debug_images文件夹中，图片名字和对应信息如下：

```python
"bar": 音符区域原图,
"bar_masked": 音符区域检测结果,
"bar_mask": 音符区域遮罩,

"pointer": 指针区域原图,
"pointer_masked": 指针区域检测结果,
"pointer_mask": 指针区域遮罩（截断后）,
"pointer_mask_original": 指针区域遮罩（未处理）,

"play_time_maskX": 倒数第X+1次弹奏的指针遮罩,
"play_time_pointerX": 倒数第X+1次弹奏的指针检测结果,
    
"no_pointer_pointerX": 连续第X次没有发现指针时的截图记录（连续3次检测不到指针就会默认该次演奏已经完毕）
"no_pointer_maskX": 上述对应的遮罩
    
"error_pointer": 出现两个以上或没有指针情况的截图记录,
"error_pointer_mask": 上述对应的遮罩
```

如果检测一开始就中断，或者演奏到一半突然中断，可以打开调试模式，再次遇到异常情况时可以根据 debug_images 中的记录进行判断，通过mask和masked来判断有否正常识别到对应的区域，**如果mask表现良好但masked没有标出则可以适当增大 config文件中对应的 tolerance 值，如果mask表现不好则说明RGB值的选取可能出现了问题。**
