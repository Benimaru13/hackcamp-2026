import cv2
import mediapipe as mp
import math
import time

class HandGestureDetector:
    def __init__(self, max_num_hands=1, min_detection_confidence=0.7, min_tracking_confidence=0.7):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=max_num_hands,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence
        )
        self.mp_draw = mp.solutions.drawing_utils

        # 【核心修改区：悬停点击 (Dwell Click) 参数】
        self.hover_start_time = 0        # 记录手指停下的那一瞬间的时间
        self.hover_start_pos = None      # 记录手指停下时的 (x, y) 坐标
        self.hover_tolerance = 25        # 允许的抖动范围（25个像素内轻微发抖不算移动）
        self.dwell_time_limit = 2.0      # 悬停 2.0 秒触发一次点击

    def _calc_dist(self, p1, p2):
        """计算两点间的像素欧氏距离"""
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    def process_frame(self, frame):
        """
        输入 OpenCV 读取的原始帧 (BGR)
        返回: (annotated_frame, result_dict)
        """
        h, w, _ = frame.shape
        # 镜像翻转，符合直觉
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb_frame)

        result_data = {
            "hand_detected": False,
            "gesture": "NONE",       # "HOVER" | "CLICK" | "SCROLL" | "NONE"
            "cursor_pos": (0, 0),    # 食指尖坐标 (x, y)
            "raw_landmarks": []      
        }

        if results.multi_hand_landmarks:
            result_data["hand_detected"] = True
            hand_landmarks = results.multi_hand_landmarks[0]
            self.mp_draw.draw_landmarks(frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)

            # 提取 21 个点的像素绝对坐标
            lm_list = []
            for lm in hand_landmarks.landmark:
                cx, cy = int(lm.x * w), int(lm.y * h)
                lm_list.append((cx, cy))
            result_data["raw_landmarks"] = lm_list

            # 常用关键点
            index_tip = lm_list[8]      # 食指尖
            index_pip = lm_list[6]      # 食指第二关节
            middle_tip = lm_list[12]    # 中指尖
            middle_pip = lm_list[10]    # 中指第二关节
            ring_tip = lm_list[16]      # 无名指尖
            pinky_tip = lm_list[20]     # 小拇指尖

            result_data["cursor_pos"] = index_tip

            # 判断手指是否向上伸直
            index_extended = index_tip[1] < index_pip[1]
            middle_extended = middle_tip[1] < middle_pip[1]
            ring_extended = ring_tip[1] < lm_list[14][1]
            pinky_extended = pinky_tip[1] < lm_list[18][1]

            # 获取当前帧的时间戳
            current_time = time.time()

            # 如果这是第一次检测到手，记录初始坐标和时间
            if self.hover_start_pos is None:
                self.hover_start_pos = index_tip
                self.hover_start_time = current_time

            # 1. 滚动模式判断（食指和中指竖起）
            if index_extended and middle_extended and not ring_extended and not pinky_extended:
                result_data["gesture"] = "SCROLL"
                # 手型变了，立刻重置悬停计时的状态
                self.hover_start_pos = index_tip
                self.hover_start_time = current_time

            # 2. 悬停点击与移动模式判断（只有食指竖起）
            elif index_extended and not middle_extended and not ring_extended and not pinky_extended:
                
                # 计算“现在的食指位置”与“开始计时时的原位”相差多远
                dist = self._calc_dist(index_tip, self.hover_start_pos)
                
                if dist < self.hover_tolerance:
                    # 手指没怎么动，说明在悬停！检查停了多久
                    if current_time - self.hover_start_time >= self.dwell_time_limit:
                        result_data["gesture"] = "CLICK"
                        
                        # 极其关键：触发点击后，必须把计时器“清零”（设为当前时间）
                        # 否则时间一直 > 2 秒，下一帧也会疯狂点鼠标
                        self.hover_start_time = current_time
                    else:
                        # 还没到 2 秒，保持移动状态
                        result_data["gesture"] = "HOVER"
                else:
                    # 距离超出了 25 像素，说明你正在大幅度移鼠标
                    # 那就把现在的坐标当做新的“悬停起点”，时间重新开始算
                    self.hover_start_pos = index_tip
                    self.hover_start_time = current_time
                    result_data["gesture"] = "HOVER"

            # 3. 其他乱七八糟的手势
            else:
                result_data["gesture"] = "NONE"
                # 收回手指时，重置状态
                self.hover_start_pos = None

        return frame, result_data