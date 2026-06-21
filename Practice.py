# 第一課：變數與資料型態
# device_name = "溫度感測器01"
# temperature = 26.5
# humidity = 60
# is_online = True

# print(device_name)
# print(temperature)
# print(humidity)
# print(is_online)

# print(type(device_name))
# print(type(temperature))
# print(type(humidity))
# print(type(is_online))

# 第二課：條件判斷
# if temperature > 30:
#     print("溫度過高，發出警報")
# elif temperature < 10:
#     print("溫度過低，發出警報")
# else:
#     print("溫度正常")

# if humidity >= 70 and is_online:
#     print("濕度偏高且裝置在線，記錄資料")

# if not is_online:
#     print("裝置離線")

# 第三課：迴圈
# readings = [26.5, 28.0, 31.2, 29.5, 33.0]

# for reading in readings:
#     if reading > 30:
#         print(f"讀值 {reading} 超過警戒值")
#     else:
#         print(f"讀值 {reading} 正常")

# count = 0
# while count < 3:
#     print(f"第 {count + 1} 次讀取")
#     count += 1

# 第四課：函式
# def check_reading(value, threshold=30):
#     if value > threshold:
#         return f"讀值 {value} 超過警戒值 {threshold}"
#     return f"讀值 {value} 正常"


# for reading in readings:
#     result = check_reading(reading)
#     print(result)

# print(check_reading(40, threshold=35))

# 第五課：字典
sensor = {
    "name": "溫度感測器01",
    "temperature": 26.5,
    "humidity": 60,
    "is_online": True,
}

print(sensor["name"])
print(sensor["temperature"])

sensor["temperature"] = 31.0
print(sensor)

sensor["location"] = "倉庫A"
print(sensor)

for key, value in sensor.items():
    print(f"{key}: {value}")
