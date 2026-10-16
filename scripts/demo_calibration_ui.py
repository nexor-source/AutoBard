"""Interactive calibration test scene; does not start services or send input."""
from pathlib import Path
from tkinter import Canvas, Tk, Toplevel, ttk

from autobard.calibration_ui import CalibrationWizard
from autobard.config import load_config
from autobard.window import enable_dpi_awareness


def main():
    enable_dpi_awareness()
    output = Path("diagnostics/20261014/calibration_ui_demo/settings.json")
    config = load_config(output)
    config["window"]["title_contains"] = "AutoBard 校准演示游戏"
    config["calibration"]["countdown_s"] = 20
    root = Tk()
    root.title("AutoBard 校准引导演示")
    root.geometry("460x190+80+100")
    game = Toplevel(root)
    game.title("AutoBard 校准演示游戏")
    game.geometry("1280x720+200+220")
    canvas = Canvas(game, bg="#192536", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(640, 130, text="校准演示场景 · 不是真实游戏", fill="#e2e8f0", font=("Microsoft YaHei UI", 28))
    canvas.create_rectangle(250, 526, 1030, 578, fill="#252525", outline="#777777")
    for y in [535, 545, 555, 565]:
        canvas.create_line(255, y, 1025, y, fill="#bbbbbb")
    for x in [340, 450, 560, 670, 780, 890, 1000]:
        canvas.create_rectangle(x - 9, 531, x + 9, 573, fill="#ebad40", outline="#ffdb60")
    canvas.create_line(315, 507, 315, 598, fill="#ffdf72", width=3)
    counter = canvas.create_text(640, 240, text="鼠标穿透测试：0 次点击", fill="white", font=("Microsoft YaHei UI", 18))
    clicks = [0]

    def clicked(event):
        clicks[0] += 1
        canvas.itemconfigure(counter, text=f"鼠标穿透测试：{clicks[0]} 次点击")
        print(f"game_click={clicks[0]} x={event.x} y={event.y}", flush=True)

    canvas.bind("<Button-1>", clicked)
    wizard = [None]
    status = ttk.Label(root, text="点击开始，再切换到演示游戏。F8 立即截图，Esc 取消。", wraplength=410)
    status.pack(padx=20, pady=20)

    def finished(kind, value):
        wizard[0] = None
        root.deiconify()
        status.configure(text=f"{kind}: {value or '演示完成'}")
        print(kind, value, flush=True)

    def start():
        if wizard[0] is not None:
            return
        root.iconify()
        wizard[0] = CalibrationWizard(root, config, output, finished)
        wizard[0].start()

    def close():
        if wizard[0] is not None:
            wizard[0].finish("calibration_cancelled", None)
        root.destroy()

    ttk.Button(root, text="开始校准演示", command=start).pack()
    ttk.Button(root, text="退出演示", command=close).pack(pady=8)
    root.protocol("WM_DELETE_WINDOW", close)
    game.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()
