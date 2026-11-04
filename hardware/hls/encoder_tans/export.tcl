set root [file normalize [file dirname [info script]]]
open_project "$root/proof"
open_solution solution1
export_design -format ip_catalog -vendor lifee.fpga -library codec -version 5.0 -output "$root/near_ip.zip"
exit
