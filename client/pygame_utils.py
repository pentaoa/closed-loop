import random
import os
import numpy as np
import pygame as pg
import time
import gc

from Jellyfish_Python_API.neuracle_api import DataServerThread
from neuracle_lib.triggerBox import TriggerBox, PackageSensorPara

class Model:
    def __init__(self):
        self.current_phase = 'waiting'
        self.current_task_index = 0
        self.current_sequence = 0
        self.total_sequences = len(images) // num_per_event
        self.sample_rate = 1000
        self.t_buffer = 1000
        self.thread_data_server = DataServerThread(self.sample_rate, self.t_buffer)
        self.flagstop = False
        self.triggerbox = TriggerBox("COM4")
        self.sequence_indices = list(range(len(images)))

    def trigger(self, label):
        code = int(label)  # 直接将传入的类别编号转换为整数
        print(f'Sending trigger for label {label}: {code}')
        self.triggerbox.output_event_data(code)

    def connect_to_jellyfish(self):
        notConnect = self.thread_data_server.connect(hostname='127.0.0.1', port=8712)
        if notConnect:
            raise Exception("Can't connect to JellyFish, please check the hostport.")
        else:
            while not self.thread_data_server.isReady():
                time.sleep(1)
                continue
            self.thread_data_server.start()

    def stop_data_collection(self):
        self.flagstop = True
        self.thread_data_server.stop()

    def save_data(self, npy_index):
        data = self.thread_data_server.GetBufferData()
        np.save(f'JiahaoTest/{time.strftime("%Y%m%d-%H%M%S")}-data-{npy_index}.npy', data)
        print("Data saved!")

    def get_next_sequence(self):
        # 确保不会超出列表范围
        if self.current_sequence * self.num_per_event >= len(self.sequence_indices):
            raise Exception("All sequences have been displayed.")

        # 从打乱的索引列表中获取下一个序列的索引
        sequence_start_index = self.current_sequence * self.num_per_event
        sequence_end_index = sequence_start_index + self.num_per_event
        next_sequence_indices = self.sequence_indices[sequence_start_index:sequence_end_index]

        # 更新当前序列计数
        self.current_sequence += 1

        # 返回选中的图像和标签，即返回 20 个 images_with_labels 元组
        return [(self.images[i], i) for i in next_sequence_indices]

    def reset_sequence(self):
        self.current_sequence = 0

    def set_phase(self, phase):
        self.current_phase = phase


class Controller:
    def __init__(self, model, view):
        self.model = model
        self.view = view

    def run(self):
        running = True
        self.model.start_data_collection()
        while running:
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    running = False
                elif event.type == pg.KEYDOWN:
                    if event.key == pg.K_ESCAPE:
                        running = False
                    elif event.key == pg.K_SPACE:
                        if self.model.current_phase == 'pre_experiment_waiting':
                            self.model.set_phase('pre_experiment_start')
                        if self.model.current_phase == 'experiment_waiting':
                            self.model.set_phase('experiment_start')

            # 等待连接到 Jellyfish
            if self.model.current_phase == 'waiting':
                self.view.display_waiting_screen()

            # 预实验等待阶段
            elif self.model.current_phase == 'pre_experiment_waiting':
                self.view.display_text('Input space to start')
                self.view.clear_screen()

            # 预实验阶段
            elif self.model.current_phase == 'pre_experiment_start':
                # TODO: pre_experiment_start phase
                time.sleep(0.75)  # 500ms 黑屏
                image_and_index = self.model.get_next_sequence()
                for image_index_pair in image_and_index:
                    image, label = image_index_pair
                    print("label: ", label)
                    self.view.display_image(image)
                    self.model.trigger(label)  # 使用图像的类别编号发送触发器
                    time.sleep(0.1)
                    self.view.display_fixation()
                    time.sleep(0.1)
                if self.model.current_sequence >= self.model.total_sequences:
                    self.model.set_phase('stop')
                else:
                    self.model.set_phase('black_screen_post')

            # 实验等待阶段
            elif self.model.current_phase == 'experiment_waiting':
                self.view.display_text('Input space to start')
                self.view.clear_screen()

            # 实验阶段
            elif self.model.current_phase == 'pre_experiment_start':
                # TODO: pre_experiment_start phase
                time.sleep(0.75)  # 500ms 黑屏
                image_and_index = self.model.get_next_sequence()
                for image_index_pair in image_and_index:
                    image, label = image_index_pair
                    print("label: ", label)
                    self.view.display_image(image)
                    self.model.trigger(label)  # 使用图像的类别编号发送触发器
                    time.sleep(0.1)
                    self.view.display_fixation()
                    time.sleep(0.1)
                if self.model.current_sequence >= self.model.total_sequences:
                    self.model.set_phase('stop')
                else:
                    self.model.set_phase('black_screen_post')

            # 眨眼时间等待按键继续
            elif self.model.current_phase == 'blink_time':
                self.view.display_text('请眨眼，准备好后按空格继续', (50, 50))
                self.waiting_for_space = True  # 开始等待空格键

            # 序列结束后的黑屏
            elif self.model.current_phase == 'black_screen_post':
                self.view.clear_screen()
                time.sleep(0.75)  # 750ms 黑屏
                self.model.set_phase('blink_time')

            # 眨眼时间
            elif self.model.current_phase == 'blink_time':
                self.view.display_text('请眨眼', (50, 50))
                time.sleep(2)  # 2秒眨眼时间
                self.model.set_phase('black_screen_pre')

            # 实验结束
            elif self.model.current_phase == 'stop':
                self.view.display_text('Thank you!')
                time.sleep(3)
                running = False

        # 在实验循环结束后停止数据收集并保存数据
        self.model.stop_data_collection()
        self.model.save_data(self.model.npy_index)  # 保存数据
        pg.quit()
        gc.collect()
        quit()

    def handle_space(self):
        # 按空格键跳转到下一个序列的开始
        if self.model.current_phase == 'blink_time':
            self.model.set_phase('black_screen_pre')


class View:
    def __init__(self):
        pg.init()
        self.screen = pg.display.set_mode((1200, 900))
        pg.display.set_caption('ExperimentTask')
        self.font = pg.font.Font(None, 32)

    def display_text(self, text):
        self.screen.fill((30, 30, 30))
        text_surface = self.font.render(text, True, (255, 255, 255))
        self.screen.blit(text_surface, (self.screen.get_width() // 2 - text_surface.get_width() // 2,
                                        self.screen.get_height() // 2 - text_surface.get_height() // 2))
        pg.display.flip()     

    def display_fixation(self):
        self.screen.fill((0, 0, 0))  # 清屏
        # 绘制红色圆
        pg.draw.circle(self.screen, (255, 0, 0), (600, 450), 30, 0)
        # 绘制黑色十字
        pg.draw.line(self.screen, (0, 0, 0), (575, 450), (625, 450), 10)
        pg.draw.line(self.screen, (0, 0, 0), (600, 425), (600, 475), 10)
        pg.display.flip()

    def display_image(self, image):
        self.screen.blit(image, (0, 0))
        pg.draw.circle(self.screen, (255, 0, 0), (600, 450), 30, 0)
        pg.draw.line(self.screen, (0, 0, 0), (575, 450), (625, 450), 10)
        pg.draw.line(self.screen, (0, 0, 0), (600, 425), (600, 475), 10)

        # 更新屏幕显示
        pg.display.flip()

    def display_text(self, text, position):
        # 使用指定的中文字体渲染文本
        font = pg.font.Font(self.font_path, 50)
        text_surface = font.render(text, True, (255, 255, 255))
        self.screen.blit(text_surface, position)
        pg.display.flip()

    def clear_screen(self):
        self.screen.fill((0, 0, 0))
        pg.display.flip()

    def display_multiline_text(self, text, position, font_size, line_spacing):
        font = pg.font.Font(self.font_path, font_size)
        lines = text.splitlines()  # 分割文本为多行
        x, y = position

        for line in lines:
            line_surface = font.render(line, True, (255, 255, 255))
            self.screen.blit(line_surface, (x, y))
            y += line_surface.get_height() + line_spacing  # 更新y坐标，为下一行做准备

        pg.display.flip()  # 更新屏幕显示
