import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timedelta
from collections import defaultdict

# Use matplotlib's dark background style
plt.style.use('dark_background')

# Modern color palette optimized for dark backgrounds
TOPIC_COLORS = {
    'Hardware Selection': '#FF6B6B',     # Coral Red
    'Analog Front-End': '#4ECDC4',       # Teal
    'PCB Design': '#45B7D1',             # Sky Blue
    'Power Management': '#FFA07A',        # Light Salmon
    'ESP32 Firmware': '#98D8C8',         # Mint
    'DSP': '#FFD93D',                    # Gold
    'GUI/Visualization': '#95E77E',      # Light Green
    'Network/Discovery': '#DDA0DD',      # Plum
    'BrainFlow Integration': '#F4A460',  # Sandy Brown
    'Documentation': '#87CEEB',          # Sky Blue
    'Testing/Debug': '#D8BFD8',          # Thistle
    'Raspberry Pi Dev': '#F0E68C',       # Khaki
    'Test & Measurement': '#BC8F8F',     # Rosy Brown
    'RF/Wireless': '#9370DB'             # Medium Purple
}

def parse_time(time_str):
    """Parse time string to datetime object"""
    return datetime.strptime(time_str, "%H:%M:%S")

def parse_date(date_str):
    """Parse date string to datetime object"""
    return datetime.strptime(date_str, "%Y-%m-%d")

def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple (0-1 range)"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4))

# Timeline data - Part 1 (Dec 2024 - July 2025)
timeline_part1 = [
    ("2024-12-05", "08:47:30", "08:51:38", ["Hardware Selection"]),
    ("2024-12-07", "19:39:42", "19:45:16", ["Hardware Selection"]),
    ("2024-12-09", "05:59:54", "06:03:11", ["DSP", "Hardware Selection"]),
    ("2024-12-09", "08:02:01", "08:02:26", ["PCB Design"]),
    ("2024-12-10", "21:27:24", "21:33:17", ["Hardware Selection"]),
    ("2024-12-17", "21:47:41", "22:59:18", ["Hardware Selection", "DSP"]),
    ("2024-12-18", "10:49:46", "11:04:32", ["DSP"]),
    ("2024-12-18", "23:49:31", "23:54:14", ["PCB Design"]),
    ("2024-12-19", "00:11:51", "00:18:53", ["PCB Design"]),
    ("2025-01-17", "01:11:46", "01:12:00", ["Hardware Selection"]),
    ("2025-01-20", "10:07:16", "10:08:00", ["Power Management"]),
    ("2025-01-20", "15:18:44", "15:19:32", ["Power Management"]),
    ("2025-01-22", "02:41:04", "02:47:29", ["Hardware Selection"]),
    ("2025-01-24", "23:04:50", "23:04:56", ["PCB Design"]),
    ("2025-01-25", "09:10:50", "09:28:55", ["PCB Design"]),
    ("2025-01-25", "19:50:06", "20:56:55", ["Hardware Selection", "Analog Front-End"]),
    ("2025-01-26", "19:09:41", "19:10:27", ["Analog Front-End"]),
    ("2025-01-26", "20:00:00", "20:50:22", ["PCB Design"]),
    ("2025-01-26", "20:58:23", "21:11:06", ["PCB Design"]),
    ("2025-01-26", "22:18:30", "23:58:14", ["Analog Front-End", "Power Management"]),
    ("2025-01-27", "00:16:46", "00:16:58", ["Analog Front-End"]),
    ("2025-01-27", "01:50:51", "01:51:06", ["PCB Design"]),
    ("2025-01-27", "09:04:27", "09:24:12", ["Power Management"]),
    ("2025-01-27", "10:36:05", "11:40:41", ["Analog Front-End"]),
    ("2025-01-27", "13:16:43", "13:24:32", ["Analog Front-End"]),
    ("2025-01-27", "14:58:33", "14:58:33", ["Hardware Selection"]),
    ("2025-01-27", "21:23:51", "23:19:28", ["Analog Front-End"]),
    ("2025-01-28", "08:13:37", "08:13:53", ["Power Management"]),
    ("2025-01-28", "11:19:34", "11:20:16", ["PCB Design"]),
    ("2025-01-28", "16:04:45", "17:14:44", ["PCB Design"]),
    ("2025-01-28", "20:12:46", "20:44:05", ["Analog Front-End"]),
    ("2025-01-28", "21:41:53", "21:54:15", ["PCB Design"]),
    ("2025-01-29", "09:22:35", "09:32:12", ["PCB Design"]),
    ("2025-01-29", "10:08:09", "10:08:16", ["Hardware Selection"]),
    ("2025-01-29", "12:59:41", "13:19:16", ["Raspberry Pi Dev"]),
    ("2025-01-29", "14:03:18", "14:03:26", ["Raspberry Pi Dev"]),
    ("2025-01-29", "14:58:00", "14:58:03", ["Raspberry Pi Dev"]),
    ("2025-01-30", "10:34:45", "11:05:58", ["Analog Front-End"]),
    ("2025-01-30", "13:14:01", "13:14:43", ["Analog Front-End"]),
    ("2025-01-31", "01:53:05", "03:10:01", ["Analog Front-End"]),
    ("2025-01-31", "14:05:54", "14:40:45", ["Analog Front-End"]),
    ("2025-01-31", "16:52:03", "16:54:13", ["Raspberry Pi Dev"]),
    ("2025-01-31", "23:28:53", "23:29:12", ["Raspberry Pi Dev"]),
    ("2025-02-01", "13:49:20", "13:55:15", ["Power Management"]),
    ("2025-02-01", "15:59:54", "16:00:11", ["Hardware Selection"]),
    ("2025-02-02", "14:50:46", "15:49:49", ["ESP32 Firmware"]),
    ("2025-02-02", "17:17:50", "17:18:04", ["Power Management"]),
    ("2025-02-03", "02:53:52", "03:05:08", ["PCB Design"]),
    ("2025-02-03", "06:45:17", "06:54:54", ["DSP"]),
    ("2025-02-03", "12:42:14", "12:43:07", ["Power Management"]),
    ("2025-02-03", "18:39:28", "19:02:30", ["ESP32 Firmware"]),
    ("2025-02-04", "07:37:27", "07:39:54", ["PCB Design"]),
    ("2025-02-04", "14:22:31", "14:25:52", ["PCB Design"]),
    ("2025-02-05", "10:49:48", "10:50:55", ["DSP"]),
    ("2025-02-05", "12:48:48", "12:55:39", ["Power Management"]),
    ("2025-02-13", "21:35:04", "21:50:09", ["Raspberry Pi Dev"]),
    ("2025-02-13", "22:54:06", "23:02:12", ["Raspberry Pi Dev"]),
    ("2025-02-14", "00:51:32", "00:53:12", ["Raspberry Pi Dev"]),
    ("2025-02-14", "02:06:37", "02:18:08", ["Raspberry Pi Dev"]),
    ("2025-02-14", "10:27:14", "10:28:07", ["Raspberry Pi Dev"]),
    ("2025-02-14", "12:54:46", "14:06:12", ["Analog Front-End"]),
    ("2025-02-14", "17:06:36", "17:20:44", ["Raspberry Pi Dev"]),
    ("2025-02-14", "18:26:12", "18:26:24", ["Raspberry Pi Dev"]),
    ("2025-02-14", "19:04:31", "19:12:01", ["Raspberry Pi Dev"]),
    ("2025-02-14", "20:26:46", "21:15:20", ["Raspberry Pi Dev"]),
    ("2025-02-14", "22:35:33", "23:56:33", ["Raspberry Pi Dev"]),
    ("2025-02-15", "00:07:27", "00:42:59", ["Raspberry Pi Dev"]),
    ("2025-02-15", "01:55:04", "02:23:49", ["Raspberry Pi Dev"]),
    ("2025-02-16", "02:08:02", "02:08:02", ["Test & Measurement"]),
    ("2025-02-16", "03:19:51", "04:17:11", ["Raspberry Pi Dev"]),
    ("2025-02-17", "04:36:13", "08:08:07", ["Raspberry Pi Dev", "PCB Design"]),
    ("2025-02-17", "11:17:17", "11:22:33", ["Hardware Selection"]),
    ("2025-02-25", "22:16:51", "03:57:30", ["ESP32 Firmware"]),
    ("2025-02-28", "08:51:51", "09:46:53", ["DSP"]),
    ("2025-03-01", "05:38:36", "06:41:54", ["GUI/Visualization"]),
    ("2025-03-08", "14:14:03", "15:27:25", ["ESP32 Firmware"]),
    ("2025-03-16", "18:52:36", "22:00:54", ["ESP32 Firmware"]),
    ("2025-03-17", "11:35:32", "11:37:19", ["Power Management"]),
    ("2025-03-18", "20:40:48", "20:42:30", ["ESP32 Firmware"]),
    ("2025-03-28", "06:45:02", "07:08:28", ["GUI/Visualization"]),
    ("2025-03-28", "21:49:46", "23:25:50", ["ESP32 Firmware"]),
    ("2025-03-29", "00:55:08", "01:10:20", ["ESP32 Firmware"]),
    ("2025-03-30", "15:58:51", "18:17:41", ["GUI/Visualization", "DSP"]),
    ("2025-04-01", "23:30:59", "23:49:46", ["Power Management"]),
    ("2025-04-02", "22:33:27", "22:44:15", ["Power Management"]),
    ("2025-04-03", "01:06:41", "01:23:24", ["DSP"]),
    ("2025-04-03", "21:09:03", "21:09:31", ["Analog Front-End"]),
    ("2025-04-04", "23:19:59", "23:20:29", ["Test & Measurement"]),
    ("2025-04-05", "00:53:35", "02:17:21", ["GUI/Visualization"]),
    ("2025-04-05", "13:33:55", "13:34:27", ["GUI/Visualization"]),
    ("2025-04-18", "00:23:11", "00:23:47", ["Hardware Selection"]),
    ("2025-04-21", "01:52:48", "02:50:34", ["Power Management"]),
    ("2025-04-21", "21:19:08", "21:31:10", ["Power Management"]),
    ("2025-04-22", "11:35:33", "12:21:22", ["PCB Design"]),
    ("2025-04-22", "14:00:22", "14:18:41", ["PCB Design"]),
    ("2025-04-22", "18:14:08", "18:15:53", ["PCB Design"]),
    ("2025-04-22", "19:35:21", "19:35:49", ["PCB Design"]),
    ("2025-04-22", "21:19:29", "21:42:11", ["ESP32 Firmware"]),
    ("2025-04-22", "23:28:51", "23:34:52", ["ESP32 Firmware"]),
    ("2025-04-23", "01:00:27", "01:01:02", ["PCB Design"]),
    ("2025-04-23", "04:48:51", "04:51:14", ["PCB Design"]),
    ("2025-04-29", "07:53:51", "08:15:31", ["RF/Wireless"]),
    ("2025-05-03", "11:21:39", "11:22:58", ["PCB Design"]),
    ("2025-05-07", "02:59:27", "03:52:52", ["PCB Design"]),
    ("2025-05-07", "05:54:59", "06:16:29", ["PCB Design"]),
    ("2025-05-07", "09:22:44", "10:09:57", ["PCB Design"]),
    ("2025-05-07", "15:19:24", "15:48:28", ["PCB Design"]),
    ("2025-05-08", "12:07:42", "12:21:51", ["RF/Wireless"]),
    ("2025-05-09", "21:23:15", "21:25:16", ["RF/Wireless"]),
    ("2025-05-10", "13:19:52", "13:21:03", ["Test & Measurement"]),
    ("2025-05-10", "17:16:32", "20:07:26", ["ESP32 Firmware"]),
    ("2025-05-12", "09:43:00", "10:02:30", ["PCB Design"]),
    ("2025-05-12", "18:44:55", "18:44:56", ["PCB Design"]),
    ("2025-05-13", "05:43:52", "08:03:05", ["Hardware Selection"]),
    ("2025-05-15", "13:58:42", "14:57:08", ["Hardware Selection"]),
    ("2025-05-16", "14:52:20", "15:09:31", ["Power Management"]),
    ("2025-05-16", "20:42:51", "21:35:59", ["ESP32 Firmware"]),
    ("2025-05-17", "12:28:59", "13:52:24", ["ESP32 Firmware", "Analog Front-End"]),
    ("2025-05-17", "20:43:27", "23:27:04", ["Test & Measurement"]),
    ("2025-05-17", "21:20:00", "21:20:01", ["DSP"]),
    ("2025-05-19", "00:45:07", "00:47:18", ["GUI/Visualization"]),
    ("2025-05-19", "21:25:46", "21:26:22", ["PCB Design"]),
    ("2025-05-20", "19:14:10", "21:36:46", ["GUI/Visualization"]),
    ("2025-05-21", "01:17:23", "01:17:30", ["GUI/Visualization"]),
    ("2025-05-21", "17:44:59", "17:46:43", ["Hardware Selection"]),
    ("2025-05-21", "19:34:18", "19:35:53", ["GUI/Visualization"]),
    ("2025-05-21", "20:49:17", "22:37:21", ["GUI/Visualization"]),
    ("2025-05-21", "23:49:58", "23:56:33", ["GUI/Visualization"]),
    ("2025-05-22", "00:05:10", "02:21:21", ["GUI/Visualization"]),
    ("2025-05-22", "09:36:05", "10:17:59", ["PCB Design"]),
    ("2025-05-22", "16:34:37", "17:46:21", ["PCB Design"]),
    ("2025-05-22", "19:25:23", "19:30:16", ["PCB Design"]),
    ("2025-05-22", "21:09:09", "21:24:50", ["PCB Design"]),
    ("2025-05-22", "21:52:04", "23:08:29", ["Test & Measurement"]),
    ("2025-05-22", "22:44:03", "22:45:07", ["Test & Measurement"]),
    ("2025-05-23", "01:02:32", "05:02:27", ["Test & Measurement"]),
    ("2025-05-23", "03:43:50", "03:47:34", ["Test & Measurement"]),
    ("2025-05-24", "15:11:34", "16:18:38", ["Hardware Selection"]),
    ("2025-05-29", "04:36:25", "08:18:42", ["Test & Measurement"]),
    ("2025-05-29", "20:34:55", "22:03:39", ["Test & Measurement"]),
    ("2025-06-10", "21:33:26", "21:33:46", ["DSP"]),
    ("2025-06-11", "09:07:18", "09:07:51", ["ESP32 Firmware"]),
    ("2025-06-11", "09:26:21", "09:41:56", ["ESP32 Firmware"]),
    ("2025-06-11", "17:51:31", "17:53:49", ["ESP32 Firmware"]),
    ("2025-06-11", "19:01:24", "20:37:41", ["ESP32 Firmware"]),
    ("2025-06-11", "22:13:07", "22:14:03", ["ESP32 Firmware"]),
    ("2025-06-11", "23:15:05", "23:52:32", ["ESP32 Firmware"]),
    ("2025-06-12", "00:09:37", "00:33:47", ["ESP32 Firmware"]),
    ("2025-06-12", "03:10:31", "04:14:40", ["ESP32 Firmware"]),
    ("2025-06-12", "07:44:20", "09:02:48", ["ESP32 Firmware"]),
    ("2025-06-12", "10:19:26", "11:24:00", ["DSP"]),
    ("2025-06-12", "10:55:29", "10:55:30", ["ESP32 Firmware"]),
    ("2025-06-12", "21:24:33", "23:55:18", ["ESP32 Firmware"]),
    ("2025-06-13", "00:04:24", "07:08:59", ["ESP32 Firmware"]),
    ("2025-06-13", "09:24:42", "10:06:56", ["GUI/Visualization"]),
    ("2025-06-13", "11:10:20", "11:10:47", ["GUI/Visualization"]),
    ("2025-06-13", "23:24:41", "23:57:43", ["ESP32 Firmware"]),
    ("2025-06-14", "00:03:01", "00:46:06", ["ESP32 Firmware"]),
    ("2025-06-14", "02:36:18", "06:41:29", ["ESP32 Firmware"]),
    ("2025-06-14", "22:31:38", "23:52:29", ["ESP32 Firmware"]),
    ("2025-06-15", "00:04:13", "06:06:03", ["ESP32 Firmware"]),
    ("2025-06-15", "06:07:46", "07:34:32", ["GUI/Visualization"]),
    ("2025-06-15", "08:59:22", "12:46:35", ["GUI/Visualization"]),
    ("2025-06-15", "10:51:57", "12:46:35", ["GUI/Visualization"]),
    ("2025-06-16", "00:00:28", "02:24:59", ["ESP32 Firmware"]),
    ("2025-06-16", "04:42:56", "06:31:25", ["ESP32 Firmware"]),
    ("2025-06-16", "08:33:23", "08:36:11", ["DSP"]),
    ("2025-06-16", "09:36:44", "11:46:29", ["ESP32 Firmware"]),
    ("2025-06-16", "21:28:58", "22:57:36", ["DSP"]),
    ("2025-06-16", "22:57:26", "23:55:56", ["DSP"]),
    ("2025-06-17", "00:06:10", "04:51:02", ["DSP", "ESP32 Firmware"]),
    ("2025-06-17", "06:07:04", "09:36:28", ["ESP32 Firmware"]),
    ("2025-06-17", "11:54:45", "13:27:06", ["ESP32 Firmware"]),
    ("2025-06-17", "12:02:04", "12:07:59", ["GUI/Visualization"]),
    ("2025-06-17", "14:43:41", "17:19:48", ["DSP"]),
    ("2025-06-17", "23:59:58", "23:59:58", ["ESP32 Firmware"]),
    ("2025-06-18", "00:00:11", "02:22:53", ["ESP32 Firmware"]),
    ("2025-06-18", "01:03:56", "04:39:59", ["ESP32 Firmware", "DSP"]),
    ("2025-06-18", "08:11:17", "10:19:52", ["ESP32 Firmware"]),
    ("2025-06-18", "11:56:49", "18:00:00", ["ESP32 Firmware"]),
    ("2025-06-18", "17:51:56", "19:14:10", ["ESP32 Firmware"]),
    ("2025-06-19", "00:48:54", "04:01:11", ["DSP"]),
    ("2025-06-19", "01:55:34", "01:55:51", ["ESP32 Firmware"]),
    ("2025-06-19", "03:00:53", "03:01:14", ["DSP"]),
    ("2025-06-19", "05:28:00", "08:00:26", ["ESP32 Firmware"]),
    ("2025-06-19", "05:50:32", "06:28:20", ["DSP"]),
    ("2025-06-19", "12:48:04", "18:00:14", ["DSP", "ESP32 Firmware"]),
    ("2025-06-19", "14:51:57", "16:41:08", ["ESP32 Firmware"]),
    ("2025-06-19", "19:29:34", "19:29:37", ["ESP32 Firmware"]),
    ("2025-06-20", "00:13:08", "03:04:04", ["ESP32 Firmware"]),
    ("2025-06-20", "00:56:58", "01:00:31", ["ESP32 Firmware"]),
    ("2025-06-20", "03:03:41", "03:42:30", ["ESP32 Firmware"]),
    ("2025-06-20", "07:20:28", "09:42:40", ["ESP32 Firmware"]),
    ("2025-06-20", "10:20:19", "12:17:05", ["DSP"]),
    ("2025-06-20", "14:39:48", "21:43:25", ["DSP"]),
    ("2025-06-21", "03:45:47", "16:45:10", ["ESP32 Firmware", "DSP"]),
    ("2025-06-21", "15:35:49", "17:19:06", ["ESP32 Firmware"]),
    ("2025-06-22", "05:18:07", "08:27:39", ["ESP32 Firmware"]),
    ("2025-06-22", "09:09:17", "16:49:01", ["ESP32 Firmware"]),
    ("2025-06-23", "01:31:52", "08:20:23", ["ESP32 Firmware"]),
    ("2025-06-24", "02:28:35", "03:27:18", ["ESP32 Firmware"]),
    ("2025-06-24", "02:31:37", "04:27:46", ["ESP32 Firmware"]),
    ("2025-06-24", "04:31:00", "05:07:33", ["ESP32 Firmware"]),
    ("2025-06-24", "05:44:37", "09:28:51", ["ESP32 Firmware"]),
    ("2025-06-24", "06:22:05", "06:29:48", ["ESP32 Firmware"]),
    ("2025-06-24", "08:45:16", "09:29:55", ["ESP32 Firmware"]),
    ("2025-06-24", "11:40:40", "11:44:04", ["ESP32 Firmware"]),
    ("2025-06-24", "11:46:03", "12:42:18", ["ESP32 Firmware"]),
    ("2025-06-27", "04:37:42", "07:41:35", ["GUI/Visualization"]),
    ("2025-06-28", "16:42:14", "18:30:00", ["DSP"]),
    ("2025-06-29", "20:57:50", "22:27:46", ["Analog Front-End", "DSP"]),
    ("2025-07-01", "20:12:05", "20:19:07", ["ESP32 Firmware"]),
    ("2025-07-01", "22:33:38", "23:08:02", ["ESP32 Firmware"]),
    ("2025-07-02", "08:08:28", "08:46:05", ["GUI/Visualization"]),
    ("2025-07-04", "09:13:41", "18:56:47", ["ESP32 Firmware"]),
    ("2025-07-04", "16:03:14", "16:09:10", ["DSP"]),
    ("2025-07-04", "21:04:10", "23:44:46", ["ESP32 Firmware"]),
    ("2025-07-05", "00:30:48", "01:41:33", ["ESP32 Firmware"]),
    ("2025-07-05", "17:46:38", "17:47:19", ["ESP32 Firmware"]),
    ("2025-07-05", "22:09:36", "23:27:40", ["ESP32 Firmware"]),
    ("2025-07-06", "22:06:43", "22:36:30", ["Analog Front-End"]),
    ("2025-07-08", "00:32:50", "00:32:54", ["ESP32 Firmware"]),
    ("2025-07-08", "11:29:47", "13:43:39", ["PCB Design"]),
    ("2025-07-08", "21:03:35", "23:45:54", ["GUI/Visualization"]),
    ("2025-07-09", "00:00:01", "01:43:29", ["GUI/Visualization"]),
    ("2025-07-09", "00:22:27", "01:00:49", ["GUI/Visualization"]),
    ("2025-07-09", "12:29:56", "13:17:27", ["ESP32 Firmware"]),
    ("2025-07-09", "20:17:35", "23:38:55", ["GUI/Visualization"]),
    ("2025-07-10", "00:00:59", "00:44:07", ["GUI/Visualization"]),
    ("2025-07-10", "18:59:20", "19:42:41", ["GUI/Visualization"]),
    ("2025-07-10", "19:29:21", "19:30:54", ["GUI/Visualization"]),
    ("2025-07-10", "21:12:15", "23:34:45", ["GUI/Visualization"]),
    ("2025-07-11", "13:18:14", "13:18:51", ["ESP32 Firmware", "GUI/Visualization"]),
    ("2025-07-11", "14:45:25", "14:45:32", ["ESP32 Firmware"]),
    ("2025-07-11", "16:02:24", "17:32:00", ["GUI/Visualization"]),
    ("2025-07-11", "21:19:47", "21:19:47", ["GUI/Visualization"]),
    ("2025-07-11", "21:36:10", "22:08:31", ["GUI/Visualization"]),
    ("2025-07-11", "22:37:53", "22:41:24", ["ESP32 Firmware"]),
    ("2025-07-12", "14:44:30", "16:28:40", ["GUI/Visualization"]),
    ("2025-07-12", "23:25:17", "23:53:44", ["GUI/Visualization"]),
    ("2025-07-13", "00:15:20", "00:19:48", ["GUI/Visualization"]),
    ("2025-07-13", "01:07:25", "01:35:02", ["GUI/Visualization"]),
    ("2025-07-14", "08:26:14", "08:26:15", ["GUI/Visualization"]),
    ("2025-07-14", "12:02:07", "12:22:32", ["ESP32 Firmware"]),
    ("2025-07-14", "13:40:44", "13:45:21", ["GUI/Visualization"]),
    ("2025-07-15", "01:29:26", "01:50:41", ["ESP32 Firmware"]),
    ("2025-07-15", "09:29:27", "09:52:30", ["GUI/Visualization"]),
    ("2025-07-15", "10:29:26", "10:51:16", ["GUI/Visualization"]),
]

# Timeline data - Part 2 (continuation)
timeline_part2 = [
    ("2025-07-11", "14:02:16", "16:57:29", ["Documentation", "Hardware Selection"]),
    ("2025-07-11", "19:39:56", "21:35:04", ["GUI/Visualization"]),
    ("2025-07-12", "13:37:01", "14:43:14", ["GUI/Visualization"]),
    ("2025-07-12", "15:50:35", "18:45:11", ["GUI/Visualization"]),
    ("2025-07-12", "22:25:34", "23:58:31", ["GUI/Visualization", "DSP"]),
    ("2025-07-13", "00:01:51", "01:03:19", ["GUI/Visualization"]),
    ("2025-07-13", "16:25:39", "19:17:20", ["GUI/Visualization", "DSP"]),
    ("2025-07-13", "21:10:20", "22:33:35", ["GUI/Visualization"]),
    ("2025-07-14", "00:04:02", "00:13:01", ["GUI/Visualization"]),
    ("2025-07-14", "07:59:01", "08:38:48", ["GUI/Visualization"]),
    ("2025-07-14", "13:50:43", "14:10:07", ["GUI/Visualization"]),
    ("2025-07-15", "01:03:36", "03:56:51", ["GUI/Visualization", "Analog Front-End"]),
    ("2025-07-15", "13:33:15", "15:09:51", ["BrainFlow Integration"]),
    ("2025-07-15", "18:20:40", "19:53:49", ["BrainFlow Integration", "Network/Discovery"]),
    ("2025-07-16", "17:54:38", "23:27:07", ["BrainFlow Integration", "GUI/Visualization"]),
    ("2025-07-17", "00:00:34", "00:36:36", ["BrainFlow Integration"]),
    ("2025-07-17", "02:53:09", "07:44:01", ["BrainFlow Integration"]),
    ("2025-07-18", "02:41:26", "07:30:07", ["BrainFlow Integration", "DSP"]),
    ("2025-07-18", "08:28:43", "11:48:24", ["Documentation"]),
    ("2025-07-19", "18:15:15", "18:16:40", ["Hardware Selection"]),
    ("2025-07-19", "19:06:38", "23:48:16", ["ESP32 Firmware", "Network/Discovery"]),
    ("2025-07-19", "23:52:02", "23:57:33", ["ESP32 Firmware"]),
    ("2025-07-20", "00:25:10", "00:27:09", ["Documentation"]),
    ("2025-07-20", "17:03:15", "17:14:57", ["ESP32 Firmware"]),
    ("2025-07-21", "02:54:06", "07:57:02", ["Hardware Selection", "Documentation"]),
    ("2025-07-21", "23:57:36", "23:57:54", ["Testing/Debug"]),
    ("2025-07-22", "00:05:43", "00:22:23", ["Analog Front-End"]),
    ("2025-07-22", "22:17:58", "22:20:14", ["GUI/Visualization"]),
    ("2025-07-23", "22:42:44", "23:37:14", ["Analog Front-End"]),
    ("2025-07-24", "00:01:12", "02:24:17", ["ESP32 Firmware", "Analog Front-End"]),
    ("2025-07-24", "02:26:10", "04:22:27", ["ESP32 Firmware"]),
    ("2025-07-24", "09:32:26", "09:39:57", ["Documentation"]),
    ("2025-07-24", "18:42:55", "19:37:41", ["Documentation"]),
    ("2025-07-24", "21:32:36", "23:55:31", ["ESP32 Firmware", "Analog Front-End"]),
    ("2025-07-25", "00:00:53", "01:12:25", ["ESP32 Firmware", "Analog Front-End"]),
    ("2025-07-25", "10:35:00", "12:54:04", ["ESP32 Firmware", "Documentation"]),
    ("2025-07-25", "20:25:05", "21:47:13", ["Documentation"]),
    ("2025-08-07", "00:49:13", "02:44:36", ["GUI/Visualization"]),
    ("2025-08-07", "05:53:57", "08:13:05", ["GUI/Visualization", "ESP32 Firmware"]),
    ("2025-08-07", "10:48:16", "13:06:49", ["ESP32 Firmware", "Power Management"]),
    ("2025-08-07", "20:19:07", "23:17:51", ["GUI/Visualization"]),
    ("2025-08-08", "11:41:33", "12:12:55", ["BrainFlow Integration"]),
    ("2025-08-12", "05:21:29", "05:51:30", ["GUI/Visualization"]),
    ("2025-08-13", "01:35:05", "05:58:21", ["Documentation"]),
    ("2025-08-13", "05:30:24", "08:35:24", ["Documentation"]),
    ("2025-08-13", "08:06:59", "08:35:24", ["Documentation"]),
    ("2025-08-18", "07:17:28", "07:47:08", ["Documentation"]),
]

# Combine all timeline data
all_sessions = timeline_part1 + timeline_part2

# Create data structure for heatmap
date_hour_topics = defaultdict(lambda: defaultdict(set))

for session in all_sessions:
    date_str, start_time, end_time, topics = session
    date = parse_date(date_str)
    
    # Parse start and end times
    start = parse_time(start_time)
    end = parse_time(end_time)
    
    # Handle sessions that span across midnight
    if end < start:
        # Session goes past midnight
        for hour in range(start.hour, 24):
            for topic in topics:
                date_hour_topics[date][hour].add(topic)
        next_date = date + timedelta(days=1)
        for hour in range(0, end.hour + 1):
            for topic in topics:
                date_hour_topics[next_date][hour].add(topic)
    else:
        # Normal session within same day
        start_hour = start.hour
        end_hour = end.hour if end.minute > 0 or end.second > 0 else end.hour - 1
        for hour in range(start_hour, end_hour + 1):
            for topic in topics:
                date_hour_topics[date][hour].add(topic)

# Get date range
all_dates = sorted(date_hour_topics.keys())
if all_dates:
    min_date = all_dates[0]
    max_date = all_dates[-1]
    
    # Create complete date range
    date_range = []
    current_date = min_date
    while current_date <= max_date:
        date_range.append(current_date)
        current_date += timedelta(days=1)
    
    # Create heatmap data
    num_days = len(date_range)
    num_hours = 24
    
    # Initialize heatmap with black (0,0,0)
    heatmap = np.zeros((num_days, num_hours, 3))
    
    # Fill in the heatmap
    for day_idx, date in enumerate(date_range):
        if date in date_hour_topics:
            for hour in range(24):
                if hour in date_hour_topics[date]:
                    topics = date_hour_topics[date][hour]
                    if topics:
                        # Use the first topic's color
                        topic = list(topics)[0]
                        if topic in TOPIC_COLORS:
                            color = hex_to_rgb(TOPIC_COLORS[topic])
                            heatmap[day_idx, hour] = color
    
    # Calculate days per subplot and padding if needed
    days_per_subplot = -(-num_days // 4)  # Ceiling division
    total_padded_days = days_per_subplot * 4
    padding_needed = total_padded_days - num_days
    
    # Pad heatmap and date_range if needed
    if padding_needed > 0:
        padding = np.zeros((padding_needed, 24, 3))
        heatmap_padded = np.vstack([heatmap, padding])
        last_date = date_range[-1]
        padded_dates = [last_date + timedelta(days=i+1) for i in range(padding_needed)]
        date_range_padded = date_range + padded_dates
    else:
        heatmap_padded = heatmap
        date_range_padded = date_range
    
    # Split into 4 parts
    parts = []
    date_parts = []
    for i in range(4):
        start_idx = i * days_per_subplot
        end_idx = (i + 1) * days_per_subplot
        parts.append(heatmap_padded[start_idx:end_idx])
        date_parts.append(date_range_padded[start_idx:end_idx])
    
    # Create figure - let matplotlib handle the layout
    fig, axes = plt.subplots(1, 4, figsize=(10, 8), tight_layout=True)
    fig.patch.set_facecolor('#0a0a0a')
    
    # Add main title 
    fig.suptitle('Timeline Heatmaps (Dec 2024 - August 2025)', 
                 fontsize=20, fontweight='bold', color='#FFFFFF', y=0.93)
    
    # Process each subplot
    for i in range(4):
        ax = axes[i]
        ax.set_facecolor('#0a0a0a')
        
        # Display the heatmap
        im = ax.imshow(parts[i], aspect='equal', interpolation='nearest')
        
        # Set subplot title
        ax.set_title(f'Part {i+1}', fontsize=10, color='#FFFFFF')
        
        # Set x-axis (hours)
        ax.set_xlabel('Hour', fontsize=10, color='#CCCCCC')
        ax.set_xticks(range(0, 24, 3))
        ax.set_xticklabels(range(0, 24, 3), fontsize=8, color='#AAAAAA')
        
        # Set y-axis (dates) - SHOW ON ALL PLOTS
        ax.set_ylabel('Date', fontsize=10, color='#CCCCCC')
        
        date_labels = [date.strftime('%y/%m/%d') for date in date_parts[i]]
        step = max(1, len(date_labels) // 12)
        y_ticks = list(range(0, len(date_labels), step))
        ax.set_yticks(y_ticks)
        ax.set_yticklabels([date_labels[j] for j in y_ticks], fontsize=7, color='#AAAAAA')
        
        # Add subtle grid
        ax.grid(True, which='major', linestyle=':', linewidth=0.3, alpha=0.2, color='#333333')
        
        # Style the spines
        for spine in ax.spines.values():
            spine.set_edgecolor('#333333')
            spine.set_linewidth(0.5)
        
        # Set tick parameters
        ax.tick_params(colors='#AAAAAA', which='both', labelsize=7, length=3, width=0.5)
    
    # Create legend elements
    legend_elements = []
    for topic, color in TOPIC_COLORS.items():
        legend_elements.append(mpatches.Patch(facecolor=hex_to_rgb(color), 
                                              edgecolor='#444444', 
                                              label=topic))
    
    # Add legend at the bottom - let matplotlib figure out the position
    fig.legend(handles=legend_elements,
               loc='lower center',
               ncol=7,
               title="Topics",
               fontsize=9,
               facecolor='#1a1a1a',
               edgecolor='#333333',
               framealpha=0.95)
    
    # Just use tight layout, no manual adjustments
    #plt.tight_layout()
    
    # Save with black background
    #plt.savefig('bci_work_heatmap_4parts.png', dpi=300, bbox_inches='tight', facecolor='#0a0a0a', edgecolor='none')
    print("Heatmap saved as 'bci_work_heatmap_4parts.png'")
    
    # Print statistics
    total_sessions = len(all_sessions)
    total_days = len([d for d in date_hour_topics if date_hour_topics[d]])
    print(f"\nOverall Statistics:")
    print(f"Total Sessions: {total_sessions}")
    print(f"Total Days Worked: {total_days}")
    print(f"Date Range: {date_range[0].strftime('%Y-%m-%d')} to {date_range[-1].strftime('%Y-%m-%d')}")
    if padding_needed > 0:
        print(f"Note: Added {padding_needed} blank days to Part 4 for equal sizing")
    
    plt.show()
else:
    print("No timeline data found!")