#ifndef __SRAM_H__
#define __SRAM_H__

extern int totalstatesize;		//how much SRAM is used
extern u32 sram_owner;

typedef struct {
	u16 size;	//header+data
	u16 type;	//=STATESAVE or SRAMSAVE
	u32 uncompressed_size;
	u32 framecount;
	u32 checksum;
	char title[32];
} stateheader;

typedef struct {		//(modified stateheader)
	u16 size;
	u16 type;	//=CONFIGSAVE
	char unused1;
	char palettebank;
	char misc;
	char reserved3;
	u32 sram_checksum;	//checksum of rom using SRAM e000-ffff	
	u32 zero;	//=0
	char reserved4[32];  //="CFG", then the software-RTC epoch (#49 item 5)
} configdata;

//Where the persisted software-RTC clock lives inside configdata.reserved4.
//The template only ever fills the first four bytes ("CFG"), so this adds no
//field and does not change the record's size -- other Goomba-family forks
//that share this layout keep reading it unchanged, and the magic distinguishes
//a clock we wrote from their zeroes.
#define RTC_EPOCH_MAGIC     "RTC1"
#define RTC_EPOCH_MAGIC_OFF 8
#define RTC_EPOCH_OFF       12

u32 rtc_get_epoch(void);          //rtc.c
void rtc_restore_epoch(u32 seconds);

void bytecopy(u8 *dst,u8 *src,int count);
void flush_end_sram(void);
void getsram(void);

u32 checksum_this(void);
u32 checksum_mem(u8 *p);

void writeerror(void);
int updatestates(int index,int erase,int type);
int twodigits(int n,char *s);
void getstatetimeandsize(char *s,int time,u32 size,u32 freespace);
stateheader* drawstates(int menutype,int *menuitems,int *menuoffset, int needed_size);
void managesram(void);
void savestatemenu(void);
int findstate(u32 checksum,int type,stateheader **stateptr);
int using_flashcart(void);
void quickload(void);
void quicksave(void);
int backup_gb_sram(int called_from);
int get_saved_sram(void);
void register_sram_owner(void);
void no_sram_owner(void);
void setup_sram_after_loadstate(void);
void loadstatemenu(void);
void writeconfig(void);
void readconfig(void);

static __inline u32 get_sram_owner()
{
	return sram_owner;
}

#endif
