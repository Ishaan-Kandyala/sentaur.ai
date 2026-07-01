import requests
import os

def get_weather(city):
    key = os.getenv("OPENWEATHER_KEY")
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={key}&units=metric"
    return requests.get(url).json()

def outfit_for(temp):
    if temp < 10:
        return "Wear a warm jacket, jeans, and maybe gloves."
    if temp < 20:
        return "A hoodie or light jacket is perfect."
    if temp < 30:
        return "T-shirt and jeans will be comfortable."
    return "It’s hot — wear shorts and stay hydrated."