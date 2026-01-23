import socket
s = socket.socket()
s.bind(('0.0.0.0', 5555))
print("Bind OK")
s.close()