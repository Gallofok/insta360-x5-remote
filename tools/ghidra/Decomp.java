// Ghidra post-script: decompile functions that call accept/getpeername and the conn_monitor area
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import java.util.*;

public class Decomp extends GhidraScript {
  public void run() throws Exception {
    DecompInterface di = new DecompInterface();
    di.openProgram(currentProgram);
    FunctionManager fm = currentProgram.getFunctionManager();
    // find PLT/import funcs of interest
    Set<Function> targets = new LinkedHashSet<>();
    String[] names = {"accept","getpeername"};
    for (Function f : fm.getFunctions(true)) {
      String n = f.getName();
      for (String nm : names) {
        if (n.equals(nm) || n.startsWith(nm+"@") || n.equals("_"+nm)) {
          // find callers
          Reference[] refs = getReferencesTo(f.getEntryPoint());
          for (Reference r : refs) {
            Function caller = fm.getFunctionContaining(r.getFromAddress());
            if (caller!=null) targets.add(caller);
          }
        }
      }
    }
    println("=== functions calling accept/getpeername: "+targets.size());
    for (Function f : targets) {
      println("\n########## FUNCTION "+f.getName()+" @ "+f.getEntryPoint());
      DecompileResults dr = di.decompileFunction(f, 60, monitor);
      if (dr!=null && dr.decompileCompleted()) {
        println(dr.getDecompiledFunction().getC());
      } else println("(decompile failed)");
    }
  }
}
