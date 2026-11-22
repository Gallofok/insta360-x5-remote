import struct,sys
d=open('instaAIP','rb').read()
# ELF PT_LOAD map
e_phoff=struct.unpack('<Q',d[32:40])[0]; e_phnum=struct.unpack('<H',d[56:58])[0]
loads=[]
for i in range(e_phnum):
    o=e_phoff+i*56; p=d[o:o+56]
    if struct.unpack('<I',p[0:4])[0]==1:
        loads.append((struct.unpack('<Q',p[8:16])[0],struct.unpack('<Q',p[16:24])[0],struct.unpack('<Q',p[32:40])[0]))
def off2va(o):
    for po,pv,ps in loads:
        if po<=o<po+ps: return pv+(o-po)
def va2off(v):
    for po,pv,ps in loads:
        if pv<=v<pv+ps: return po+(v-pv)
# find .text range
# section headers
e_shoff=struct.unpack('<Q',d[40:48])[0]; shentsize=struct.unpack('<H',d[58:60])[0]; shnum=struct.unpack('<H',d[60:62])[0]; shstrndx=struct.unpack('<H',d[62:64])[0]
sh=[d[e_shoff+i*shentsize:e_shoff+(i+1)*shentsize] for i in range(shnum)]
strtab_off=struct.unpack('<Q',sh[shstrndx][24:32])[0]
def secname(s):
    n=struct.unpack('<I',s[0:4])[0]; e=d.index(b'\0',strtab_off+n); return d[strtab_off+n:e].decode()
text=None
for s in sh:
    if secname(s)=='.text':
        text=(struct.unpack('<Q',s[16:24])[0],struct.unpack('<Q',s[24:32])[0],struct.unpack('<Q',s[32:40])[0]) # addr,off,size
taddr,toff,tsize=text
target=int(sys.argv[1],16)
# scan text for ADRP (x) then matching ADD/LDR with imm12 == low bits reaching target page
# ADRP: bits: op=1, immlo[30:29], 10000, immhi[23:5], Rd[4:0]
res=[]
code=d[toff:toff+tsize]
# track last adrp per register
import collections
lastadrp={}
for i in range(0,len(code),4):
    w=struct.unpack('<I',code[i:i+4])[0]; va=taddr+i
    if (w & 0x9f000000)==0x90000000:  # ADRP
        rd=w&31
        immlo=(w>>29)&3; immhi=(w>>5)&0x7ffff
        imm=((immhi<<2)|immlo)
        if imm & (1<<20): imm-=(1<<21)
        page=(va & ~0xfff)+(imm<<12)
        lastadrp[rd]=page
    elif (w & 0x7f800000)==0x11000000:  # ADD (imm) 32/64
        rn=(w>>5)&31; rd=w&31; imm12=(w>>10)&0xfff; sh12=(w>>22)&1
        if sh12: imm12<<=12
        if rn in lastadrp and lastadrp[rn]+imm12==target:
            res.append((va,'ADD'))
    elif (w & 0x3b000000)==0x39000000 or (w & 0x3fc00000)==0xf9400000: # LDR unsigned offset (64)
        rn=(w>>5)&31; imm12=((w>>10)&0xfff); size=(w>>30)&3; imm=imm12<<size
        if rn in lastadrp and lastadrp[rn]+imm==target:
            res.append((va,'LDR'))
for va,k in res: print(hex(va),k)
print("total",len(res))
