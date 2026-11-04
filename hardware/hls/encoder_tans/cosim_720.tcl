# Re-run C/RTL co-simulation on the existing csynth (no -reset, so the
# exported IP's RTL is the one simulated).
set root [file normalize [file dirname [info script]]]
open_project "$root/proof"
open_solution solution1
cosim_design -rtl verilog -argv "--rtl720" -random_stall -trace_level none
exit
