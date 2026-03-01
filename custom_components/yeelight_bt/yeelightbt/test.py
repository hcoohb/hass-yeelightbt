import struct

class TT():
    tt = "ff"
    tt2 = ["yo"]

    def tel(self):
        print(self.tt2)

class TT2(TT):
    tt2=[0x02]
    tt3=["jj"]

print(TT2().tt2)
print(TT2().tt3)
TT2().tel()



data = b'CQ\x01\x00\rYeelight Beds'
data2 = b'ide Lamp\x00\x00\x00\x00\x00'
idx = data[3]
name = data[5:].decode("ascii")
print(f"Name: {name} from data: {data}")
print(struct.unpack_from(">xBx13s", data, 2)[1].decode("ascii"))
print(b''.join([data,data2]))
print(data.hex())
print("test"[:2])
h=10
# print(f"{data:#04x}")

data = bytes.fromhex("43450101646464002300001d000000000000")
print(data.hex())
# 4345  01  01  64  64  64  00  22  0000  1d000000000000
print(struct.unpack_from('>BBBBBxBH', data, 2))


data = bytes.fromhex("43450202000000001117661e000000000000")
print(data.hex())
# 4345  02  02  00  00  00  00  11  1766  1e000000000000
print(struct.unpack_from('>BBBBBxBH', data, 2))

data = bytes.fromhex("43450102000000002217661e000000000000 ")
print(data.hex())
# 4345  02  02  00  00  00  00  11  1766  1e000000000000
print(struct.unpack_from('>BBBBBxBH', data, 2))
 