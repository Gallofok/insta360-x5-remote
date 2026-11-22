package main
import ("encoding/binary";"fmt";"net";"os";"time")
func main(){
 // args: <srcIP> <dstIP:6666>
 src:=os.Args[1]; dst:=os.Args[2]
 la,_:=net.ResolveTCPAddr("tcp",src+":0")
 ra,_:=net.ResolveTCPAddr("tcp",dst)
 d:=net.Dialer{LocalAddr:la,Timeout:6*time.Second}
 c,err:=d.Dial("tcp",ra.String())
 if err!=nil{fmt.Println("DIAL_FAIL",err);return}
 defer c.Close()
 magic:=[]byte("syNceNdinS")
 pay:=append([]byte{0x06,0x00,0x00},magic...)
 hdr:=make([]byte,4); binary.LittleEndian.PutUint32(hdr,uint32(len(pay)+4))
 c.Write(hdr); c.Write(pay)
 c.SetReadDeadline(time.Now().Add(6*time.Second))
 buf:=make([]byte,64); n,err:=c.Read(buf)
 if err!=nil{fmt.Println("NO_REPLY (gate blocked)",err);return}
 fmt.Printf("REPLY %d bytes: %x  -> GATE PASSED from %s\n",n,buf[:n],src)
}
