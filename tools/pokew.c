/* write a 32-bit word at a file offset of a PIE process' exe mapping.
   usage: pokew <pid> <exe> <hexoff> <hexword32> */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <unistd.h>
#include <errno.h>
static unsigned long find(pid_t pid,const char*n,unsigned long fo){
 char p[64];snprintf(p,sizeof p,"/proc/%d/maps",pid);FILE*f=fopen(p,"r");if(!f)return 0;
 char l[512];unsigned long r=0,s,e,o;char pr[8],pa[256];
 while(fgets(l,sizeof l,f)){pa[0]=0;if(sscanf(l,"%lx-%lx %7s %lx %*s %*s %255s",&s,&e,pr,&o,pa)<5)continue;
  if(pr[2]!='x'||!strstr(pa,n))continue; if(fo>=o&&s+(fo-o)<e){r=s+(fo-o);break;}}
 fclose(f);return r;}
int main(int c,char**v){
 if(c<5){fprintf(stderr,"usage: %s pid exe hexoff hexword\n",v[0]);return 2;}
 pid_t pid=atoi(v[1]); unsigned long fo=strtoul(v[3],0,16),val=strtoul(v[4],0,16);
 if(ptrace(PTRACE_ATTACH,pid,0,0)<0){perror("ATTACH");return 1;} waitpid(pid,0,0);
 unsigned long a=find(pid,v[2],fo); if(!a){fprintf(stderr,"no map\n");ptrace(PTRACE_DETACH,pid,0,0);return 1;}
 unsigned long base=a&~7UL;int sh=(a&7)?32:0; errno=0;
 long w=ptrace(PTRACE_PEEKTEXT,pid,(void*)base,0);
 unsigned long nw=((unsigned long)w & ~(0xFFFFFFFFUL<<sh))|((val&0xFFFFFFFFUL)<<sh);
 ptrace(PTRACE_POKETEXT,pid,(void*)base,(void*)nw);
 long ck=ptrace(PTRACE_PEEKTEXT,pid,(void*)base,0);
 printf("off 0x%lx -> 0x%lx wrote %08lx (now %08lx)\n",fo,a,val,((unsigned long)ck>>sh)&0xFFFFFFFF);
 ptrace(PTRACE_DETACH,pid,0,0);return 0;}
