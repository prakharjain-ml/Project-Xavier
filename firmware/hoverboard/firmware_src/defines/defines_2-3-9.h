// HackPrinceton 2026 - YK187 split board with GD32E235 (runs the GD32E230 TARGET 3 build)
// Hall pins found 2026-11-14 by turning the wheel by hand and watching GPIO input registers:
//   PA0, PF1, PC15  (sequence one direction, as (PA0,PF1,PC15): 010 011 001 101 100 110)
// VBATT PA4 confirmed by autodetect reading ~31 V. Everything else copied from layout 2-3-2 / 2-3-1
// (same E230 board family) and not yet verified.
//
// Test variants selected with build flags:
//   HP_HALL_PERM 0..5  : which of PA0/PF1/PC15 is HALL_A/B/C
//   HP_HILO_SWAP 0/1   : 0 = like 2-3-2 (GH=PA10), 1 = like 2-3-1 (GH=PB15, hi/lo swapped)

#ifndef HP_HALL_PERM
	#define HP_HALL_PERM 2		// test03 = smoothest (2026-11-14)
#endif
#ifndef HP_HILO_SWAP
	#define HP_HILO_SWAP 0
#endif

#if HP_HALL_PERM == 0
	#define HALL_A PA0
	#define HALL_B PF1
	#define HALL_C PC15
#elif HP_HALL_PERM == 1
	#define HALL_A PA0
	#define HALL_B PC15
	#define HALL_C PF1
#elif HP_HALL_PERM == 2
	#define HALL_A PF1
	#define HALL_B PA0
	#define HALL_C PC15
#elif HP_HALL_PERM == 3
	#define HALL_A PF1
	#define HALL_B PC15
	#define HALL_C PA0
#elif HP_HALL_PERM == 4
	#define HALL_A PC15
	#define HALL_B PA0
	#define HALL_C PF1
#else
	#define HALL_A PC15
	#define HALL_B PF1
	#define HALL_C PA0
#endif

#define PHASE_A         PB0		// from 2-3-2, not verified
#define PHASE_B         PB1		// from 2-3-2, not verified

#define VBATT           PA4		// confirmed
#define CURRENT_DC      PA6		// from 2-3-1/2-3-2, not verified
#define SELF_HOLD       PB2		// from 2-3-1/2-3-2, not verified
// BUTTON not defined on purpose: DISABLE_BUTTON is used for now (button bridged / board on charger)

// Brushless Control DC (BLDC) defines
#if HP_HILO_SWAP == 0
	#define BLDC_GH PA10
	#define BLDC_GL PB15
	#define BLDC_BH PA9
	#define BLDC_BL PB14
	#define BLDC_YH PA8
	#define BLDC_YL PB13
#else
	#define BLDC_GH PB15
	#define BLDC_GL PA10
	#define BLDC_BH PB14
	#define BLDC_BL PA9
	#define BLDC_YH PB13
	#define BLDC_YL PA8
#endif
#define TIMER_BLDC_PULLUP	GPIO_PUPD_NONE

// USART0 = PB6/PB7 (ESP32 later), USART1 = PA2/PA3 (master-slave cable)
#define USART0_TX	PB6
#define USART0_RX	PB7
#define USART1_TX	PA2
#define USART1_RX	PA3
