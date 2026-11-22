import struct,sys
d=open(sys.argv[1],'rb').read(); n=int(sys.argv[2]) if len(sys.argv)>2 else 40
i=0;k=0;stats={}
while i+4<=len(d):
    L=struct.unpack('<I',d[i:i+4])[0]
    if L<4 or i+L>len(d): print('BAD at',i,L,d[i:i+16].hex()); break
    p=d[i+4:i+L]; t=p[:3].hex()
    stats[t]=stats.get(t,0)+1
    if k<n: print(f'{k:3d} len={L:6d} type={t} {p[3:40].hex()}  {p[3:40]!r}'[:200])
    i+=L;k+=1
print('frames',k,'types',stats)
