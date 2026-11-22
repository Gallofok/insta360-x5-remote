/* Live in-memory NOP-patcher for a PIE process.
   Usage: poker <pid> <exe_basename> <hexoff1> [hexoff2 ...]
   For each file offset, find the executable mapping of <exe_basename> in
   /proc/<pid>/maps, compute the runtime address, and overwrite 4 bytes with
   AArch64 NOP (0xD503201F). Attaches with ptrace, pokes, detaches (process
   keeps running). Revert = restart the process. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>

static unsigned long find_runtime(pid_t pid,const char*name,unsigned long foff){
  char p[64]; snprintf(p,sizeof p,"/proc/%d/maps",pid);
  FILE*f=fopen(p,"r"); if(!f){perror("maps");return 0;}
  char line[512]; unsigned long res=0;
  while(fgets(line,sizeof line,f)){
    unsigned long start,end,off; char perms[8],path[256]={0};
    if(sscanf(line,"%lx-%lx %7s %lx %*s %*s %255s",&start,&end,perms,&off,path)<5) continue;
    if(perms[2]!='x') continue;                 /* executable mapping */
    if(!strstr(path,name)) continue;
    if(foff>=off && (start+(foff-off))<end){ res=start+(foff-off); break; }
  }
  fclose(f); return res;
}

int main(int argc,char**argv){
  if(argc<4){fprintf(stderr,"usage: %s <pid> <exe> <hexoff>...\n",argv[0]);return 2;}
  pid_t pid=atoi(argv[1]); const char*exe=argv[2];
  const unsigned long NOP=0xD503201FUL;
  if(ptrace(PTRACE_ATTACH,pid,0,0)<0){perror("ATTACH");return 1;}
  waitpid(pid,0,0);
  int rc=0;
  for(int i=3;i<argc;i++){
    unsigned long foff=strtoul(argv[i],0,16);
    unsigned long addr=find_runtime(pid,exe,foff);
    if(!addr){fprintf(stderr,"off 0x%lx: no mapping\n",foff);rc=1;continue;}
    unsigned long base=addr & ~7UL; int shift=(addr&7)?32:0;
    errno=0; long word=ptrace(PTRACE_PEEKTEXT,pid,(void*)base,0);
    if(word==-1&&errno){perror("PEEK");rc=1;continue;}
    unsigned long w=(unsigned long)word;
    w=(w & ~(0xFFFFFFFFUL<<shift)) | (NOP<<shift);
    if(ptrace(PTRACE_POKETEXT,pid,(void*)base,(void*)w)<0){perror("POKE");rc=1;continue;}
    /* verify */
    long chk=ptrace(PTRACE_PEEKTEXT,pid,(void*)base,0);
    unsigned long got=((unsigned long)chk>>shift)&0xFFFFFFFFUL;
    printf("off 0x%lx -> runtime 0x%lx : %s (now %08lx)\n",foff,addr, got==NOP?"NOP OK":"MISMATCH", got);
  }
  ptrace(PTRACE_DETACH,pid,0,0);
  return rc;
}
