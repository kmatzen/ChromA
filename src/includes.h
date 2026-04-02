#ifndef __INCLUDES_H__
#define __INCLUDES_H__

#ifdef __cplusplus
	extern "C" {
#endif

#ifndef ARRSIZE
#define ARRSIZE(xxxx) (sizeof((xxxx))/sizeof((xxxx)[0]))
#endif

#include "config.h"

#include <stdio.h>
#include <string.h>
#include "gba.h"

#include "asmcalls.h"
#include "minilzo.107/minilzo.h"
#include "main.h"
#include "ui.h"
#include "sram.h"
#include "mbclient.h"
#include "cache.h"
#include "dma.h"
#include "pocketnes_text.h"

#ifdef __cplusplus
	}
#endif

#endif
