from machine import Pin, PWM
from time import sleep

sensor = Pin(27, Pin.IN)
buzzer = Pin(25, Pin.OUT)
servo = PWM(Pin(26), freq=50)

autorizado = True  # Cambiar a True para permitir el acceso

def cerrar():
    servo.duty_ns(800000)

def abrir():
    servo.duty_ns(2200000)

def beep_corto():
    buzzer.value(1)
    sleep(0.2)
    buzzer.value(0)

def beep_rechazado():
    for _ in range(2):
        buzzer.value(1)
        sleep(0.15)
        buzzer.value(0)
        sleep(0.15)

cerrar()
buzzer.value(0)

while True:
    if sensor.value() == 0:
        print("CARRO DETECTADO")

        if autorizado:
            print("ACCESO AUTORIZADO")
            beep_corto()
            abrir()
            while sensor.value() == 0:
                sleep(0.1)
            sleep(2)
            cerrar()

        else:
            print("ACCESO RECHAZADO")
            beep_rechazado()

        sleep(1)

    sleep(0.1)
