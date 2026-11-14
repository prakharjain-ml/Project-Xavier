# Helper commands for GD32E23x / GD32E235 hoverboard chips.
#
# Why this exists: OpenOCD's stm32f1x driver does not know this chip revision
# (device id 0x23030410), treats it as an STM32F1 and decodes the option bytes
# with the wrong bit offsets. Its built-in "stm32f1x unlock" would therefore
# write a wrong USER byte (e.g. enable the hardware watchdog). These procs
# follow GigaDevice's own SDK (gd32e23x_fmc.c: ob_erase /
# ob_security_protection_config) instead.
#
# Registers (FMC base 0x40022000)
set FMC_KEY    0x40022004
set FMC_OBKEY  0x40022008
set FMC_STAT   0x4002200C
set FMC_CTL    0x40022010
set FMC_OBSTAT 0x4002201C
set FMC_WP     0x40022020
set OB_SPC_USER 0x1FFFF800

# FMC_CTL bits
set CTL_OBPG  0x10
set CTL_OBER  0x20
set CTL_START 0x40
set CTL_LK    0x80
set CTL_OBWEN 0x200
# FMC_STAT bits
set STAT_BUSY 0x01
set STAT_ERRS 0x1C ;# PGERR | PGAERR | WPERR

proc rd32 {addr} {
    return [expr {[lindex [read_memory $addr 32 1] 0]}]
}

proc fmc_wait {} {
    global FMC_STAT STAT_BUSY
    for {set i 0} {$i < 500} {incr i} {
        set st [rd32 $FMC_STAT]
        if {($st & $STAT_BUSY) == 0} { return $st }
        sleep 10
    }
    error "FMC stayed busy (timeout)"
}

# Print the real protection state, decoded the GD32E23x way.
proc gd32_status {} {
    global FMC_OBSTAT FMC_WP
    set ob [rd32 $FMC_OBSTAT]
    set wp [rd32 $FMC_WP]
    set plevel [expr {($ob >> 1) & 3}]
    set user   [expr {($ob >> 8) & 0xff}]
    set data   [expr {($ob >> 16) & 0xffff}]
    echo ""
    echo "---------------- GD32E23x status ----------------"
    echo [format "FMC_OBSTAT = 0x%08x   FMC_WP = 0x%08x" $ob $wp]
    if {$plevel == 0} {
        echo "PROTECTION : OFF  (unlocked - ready to flash)"
    } elseif {$plevel == 1} {
        echo "PROTECTION : LOW  (locked - can be unlocked with step 2)"
    } else {
        echo "PROTECTION : HIGH (!!! permanently locked - tell Claude)"
    }
    echo [format "user byte  : 0x%02x  (0xff = factory normal)" $user]
    echo [format "data       : 0x%04x" $data]
    echo "-------------------------------------------------"
    echo ""
}

# Remove security protection: erase option bytes, then write
# SPC = 0xA5 (no protection) and USER = 0xFF (factory default).
# The chip hardware mass-erases main flash when protection is removed.
proc gd32_unlock {} {
    global FMC_KEY FMC_OBKEY FMC_STAT FMC_CTL FMC_OBSTAT OB_SPC_USER
    global CTL_OBPG CTL_OBER CTL_START CTL_LK CTL_OBWEN STAT_ERRS

    set ob [rd32 $FMC_OBSTAT]
    if {(($ob >> 1) & 3) > 1} { error "Protection is HIGH - cannot unlock. Stop." }

    # unlock FMC_CTL and option-byte writing
    if {[rd32 $FMC_CTL] & $CTL_LK} {
        mww $FMC_KEY 0x45670123
        mww $FMC_KEY 0xCDEF89AB
    }
    if {([rd32 $FMC_CTL] & $CTL_OBWEN) == 0} {
        mww $FMC_OBKEY 0x45670123
        mww $FMC_OBKEY 0xCDEF89AB
    }
    set ctl [rd32 $FMC_CTL]
    if {$ctl & $CTL_LK}            { error [format "FMC still locked (CTL=0x%08x)" $ctl] }
    if {($ctl & $CTL_OBWEN) == 0}  { error [format "Option byte write not enabled (CTL=0x%08x)" $ctl] }

    mww $FMC_STAT 0x3C ;# clear old flags
    fmc_wait

    echo "Erasing option bytes..."
    mmw $FMC_CTL $CTL_OBER 0
    mmw $FMC_CTL $CTL_START 0
    set st [fmc_wait]
    mmw $FMC_CTL 0 $CTL_OBER
    if {$st & $STAT_ERRS} { error [format "Option byte erase error (STAT=0x%08x)" $st] }

    # Proven on this board (2026-11-14): a direct debugger write of 0x00FF00A5
    # DOES program the option bytes (status read OFF / user 0xff afterwards),
    # but the ST-Link reports "Failed to write memory" because the chip stalls
    # the bus while programming. So we ignore that one error and check FMC_STAT.
    echo "Writing SPC=0xA5 (no protection), USER=0xFF..."
    mmw $FMC_CTL $CTL_OBPG 0
    if {[catch {mww $OB_SPC_USER 0x00FF00A5}]} {
        echo "(ST-Link reported a write error - expected on this chip, continuing)"
    }
    sleep 200
    if {[catch {set st [fmc_wait]}]} { sleep 200; set st [fmc_wait] }
    mmw $FMC_CTL 0 $CTL_OBPG
    echo [format "FMC_STAT = 0x%08x (0x20 = done OK, 0x04/0x08/0x10 = error)" $st]
    if {$st & $STAT_ERRS} { error [format "Option byte write error (STAT=0x%08x)" $st] }

    # re-lock
    mmw $FMC_CTL 0 $CTL_OBWEN
    mmw $FMC_CTL $CTL_LK 0
    echo "Option bytes written OK. Power-cycle the board (unplug ST-Link USB) to apply."
}

# Read-only diagnosis: where is the CPU, is it stuck, what is in RAM.
proc gd32_diag {} {
    echo ""
    echo "========== DIAG =========="
    for {set i 0} {$i < 5} {incr i} {
        halt
        echo "sample $i: [reg pc]  [reg xpsr]  [reg sp]  [reg lr]"
        resume
        sleep 300
    }
    halt
    echo "--- vector table ---"
    mdw 0x08000000 4
    echo "--- HFSR / DHCSR / AIRCR / VTOR ---"
    mdw 0xE000ED2C
    mdw 0xE000EDF0
    mdw 0xE000ED0C
    mdw 0xE000ED08
    echo "--- RCU (clock) CTL0 / CFG0 ---"
    mdw 0x40021000
    mdw 0x40021004
    echo "--- RAM start ---"
    mdw 0x20000000 32
    dump_image ram_dump.bin 0x20000000 0x2000
    echo "RAM saved to ram_dump.bin"
    echo "--- reset and catch first instructions ---"
    reset halt
    echo "after reset: [reg pc]  [reg sp]"
    resume
    sleep 500
    halt
    echo "500ms after reset: [reg pc]  [reg xpsr]  [reg lr]"
    resume
    echo "=========================="
}
