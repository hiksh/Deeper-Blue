/*
 * engine.c  —  Deeper-Blue C Engine
 *
 * Single-file UCI chess engine.
 * Same algorithms as engine/minimax.py + engine/evaluation.py,
 * but with bitboard representation → ~100-300x faster than Python.
 *
 * Target: depth 12 in 10/0 time control.
 *
 * Build:
 *   gcc -O3 -march=native -o deeper_blue engine.c -lm
 *   (Windows): gcc -O3 -march=native -o deeper_blue.exe engine.c -lm
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <time.h>
#include <ctype.h>
#include "poly_random.h"

#ifdef FATHOM
#include "tbprobe.h"
static bool g_tb_enabled = false;
#endif

#ifdef _WIN32
#include <windows.h>
static int64_t get_time_ms(void) {
    FILETIME ft; GetSystemTimeAsFileTime(&ft);
    return (((int64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 10000;
}
#else
#include <sys/time.h>
static int64_t get_time_ms(void) {
    struct timeval tv; gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}
#endif

/* ================================================================
   SECTION 1: Types and constants
   ================================================================ */

typedef uint64_t BB;
typedef uint32_t Move;


/* Piece types */
#define PAWN   0
#define KNIGHT 1
#define BISHOP 2
#define ROOK   3
#define QUEEN  4
#define KING   5
#define EMPTY  6

/* Colors */
#define WHITE 0
#define BLACK 1
#define BOTH  2

/* Castling rights bits */
#define CASTLE_WK 1
#define CASTLE_WQ 2
#define CASTLE_BK 4
#define CASTLE_BQ 8

/* No square sentinel */
#define NO_SQ 64

/* Square helpers */
#define SQ(f,r)    ((r)*8+(f))
#define FILE_OF(s) ((s)&7)
#define RANK_OF(s) ((s)>>3)

/* Move encoding: bits[0-5]=from, bits[6-11]=to, bits[12-15]=flags */
#define MK_MOVE(f,t,fl)  ((Move)((f)|((t)<<6)|((fl)<<12)))
#define M_FROM(m)         ((m)&0x3F)
#define M_TO(m)           (((m)>>6)&0x3F)
#define M_FLAGS(m)        (((m)>>12)&0xF)

/* Move flags */
#define FL_QUIET   0
#define FL_DPUSH   1   /* double pawn push */
#define FL_CKS     2   /* castle kingside  */
#define FL_CQS     3   /* castle queenside */
#define FL_CAP     4   /* capture          */
#define FL_EP      5   /* en passant       */
#define FL_NPROM   8   /* knight promo     */
#define FL_BPROM   9
#define FL_RPROM   10
#define FL_QPROM   11
#define FL_NPROMC  12  /* knight promo + capture */
#define FL_BPROMC  13
#define FL_RPROMC  14
#define FL_QPROMC  15

#define IS_CAP(m)   (M_FLAGS(m)&4)
#define IS_PROM(m)  (M_FLAGS(m)&8)
#define IS_EP(m)    (M_FLAGS(m)==FL_EP)
#define IS_CASTLE(m)(M_FLAGS(m)==FL_CKS||M_FLAGS(m)==FL_CQS)
/* Promotion piece: flag bits[1:0] → 0=N,1=B,2=R,3=Q */
#define PROM_PT(m)  ((M_FLAGS(m)&3)+1)

#define MOVE_NONE 0

/* Search */
#define INF         100000
#define MATE_SCORE  30000
#define MATE_THRESH 29500
#define MAX_PLY     128
#define MAX_MOVES   256

/* TT flags */
#define TT_EXACT 0
#define TT_LOWER 1
#define TT_UPPER 2

/* Material values (centipawns) — mirrors Python PIECE_VALUES */
static const int MAT[6] = {100, 320, 330, 500, 900, 20000};

/* ================================================================
   SECTION 2: Piece-Square Tables (copied from evaluation.py)
   White a1=index 0 (a1=sq0, b1=sq1, ..., h8=sq63)
   ================================================================ */

/* fmt: off */
static const int PST_PAWN_MG[64] = {
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
};
static const int PST_PAWN_EG[64] = {
     0,  0,  0,  0,  0,  0,  0,  0,
    80, 80, 80, 80, 80, 80, 80, 80,
    50, 50, 50, 50, 50, 50, 50, 50,
    30, 30, 30, 30, 30, 30, 30, 30,
    20, 20, 20, 20, 20, 20, 20, 20,
    10, 10, 10, 10, 10, 10, 10, 10,
     5,  5,  5,  5,  5,  5,  5,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
};
static const int PST_KNIGHT[64] = {
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
};
static const int PST_BISHOP[64] = {
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
};
static const int PST_ROOK_MG[64] = {
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
};
static const int PST_QUEEN_MG[64] = {
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
};
static const int PST_KING_MG[64] = {
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
};
static const int PST_KING_EG[64] = {
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
};
/* fmt: on */

/* ================================================================
   SECTION 3: Bitboard utilities and attack tables
   ================================================================ */

static BB KNIGHT_ATK[64];
static BB KING_ATK[64];
static BB PAWN_ATK[2][64];  /* [color][sq] */
static BB RAY[64][8];       /* RAY[sq][dir]: 0=N,1=NE,2=E,3=SE,4=S,5=SW,6=W,7=NW */

#define LSB(bb)   (__builtin_ctzll(bb))
#define MSB(bb)   (63^__builtin_clzll(bb))
#define POPCOUNT(bb) (__builtin_popcountll(bb))
#define BB1(sq)   (1ULL<<(sq))

static inline BB sq_bb(int sq) { return 1ULL << sq; }
static inline int pop_lsb(BB *b) { int s = LSB(*b); *b &= *b-1; return s; }

/* File and rank masks */
static const BB FILE_A = 0x0101010101010101ULL;
static const BB RANK_1 = 0x00000000000000FFULL;
static const BB RANK_2 = 0x000000000000FF00ULL;
static const BB RANK_7 = 0x00FF000000000000ULL;
static const BB RANK_8 = 0xFF00000000000000ULL;

/* Direction offsets (sq + delta moves in that direction if on board) */
static const int DIR_DELTA[8] = {8, 9, 1, -7, -8, -9, -1, 7};
/*                                N NE  E  SE   S  SW   W  NW */

static void init_ray(int sq, int dir) {
    int delta = DIR_DELTA[dir];
    int s = sq;
    BB r = 0;
    while (1) {
        int f0 = FILE_OF(s), r0 = RANK_OF(s);
        int ns = s + delta;
        int f1 = FILE_OF(ns), r1 = RANK_OF(ns);
        /* stop if off board or file/rank wrap */
        if (ns < 0 || ns >= 64) break;
        int df = f1 - f0, dr = r1 - r0;
        /* East/West: only rank stays same */
        /* check reasonable delta */
        if (abs(df) > 1 || abs(dr) > 1) break;
        r |= sq_bb(ns);
        s = ns;
    }
    RAY[sq][dir] = r;
}

static void init_tables(void) {
    for (int sq = 0; sq < 64; sq++) {
        int f = FILE_OF(sq), r = RANK_OF(sq);

        /* Knights */
        BB n = 0;
        int kd[][2] = {{-2,-1},{-2,1},{-1,-2},{-1,2},{1,-2},{1,2},{2,-1},{2,1}};
        for (int i = 0; i < 8; i++) {
            int nf = f+kd[i][0], nr = r+kd[i][1];
            if (nf>=0&&nf<8&&nr>=0&&nr<8) n |= sq_bb(SQ(nf,nr));
        }
        KNIGHT_ATK[sq] = n;

        /* Kings */
        BB k = 0;
        for (int df=-1;df<=1;df++) for (int dr=-1;dr<=1;dr++) {
            if (!df&&!dr) continue;
            int nf=f+df, nr=r+dr;
            if (nf>=0&&nf<8&&nr>=0&&nr<8) k |= sq_bb(SQ(nf,nr));
        }
        KING_ATK[sq] = k;

        /* Pawns */
        BB pw=0, pb=0;
        if (r<7) {
            if (f>0) pw |= sq_bb(SQ(f-1,r+1));
            if (f<7) pw |= sq_bb(SQ(f+1,r+1));
        }
        if (r>0) {
            if (f>0) pb |= sq_bb(SQ(f-1,r-1));
            if (f<7) pb |= sq_bb(SQ(f+1,r-1));
        }
        PAWN_ATK[WHITE][sq] = pw;
        PAWN_ATK[BLACK][sq] = pb;

        /* Rays */
        for (int d=0;d<8;d++) init_ray(sq,d);
    }
}

/* Sliding piece attacks using precomputed rays */
/* Positive ray (dir 0,1,2,7 = N,NE,E,NW): first blocker = LSB */
/* Negative ray (dir 4,5,6,3 = S,SW,W,SE): first blocker = MSB */
static const bool IS_POS_RAY[8] = {1,1,1,0,0,0,0,1};

static inline BB ray_attacks(int sq, int dir, BB occ) {
    BB r = RAY[sq][dir];
    BB b = r & occ;
    if (!b) return r;
    if (IS_POS_RAY[dir]) {
        int blocker = LSB(b);
        return r ^ RAY[blocker][dir];
    } else {
        int blocker = MSB(b);
        return r ^ RAY[blocker][dir];
    }
}

static inline BB bishop_attacks(int sq, BB occ) {
    return ray_attacks(sq,1,occ) | ray_attacks(sq,3,occ)
         | ray_attacks(sq,5,occ) | ray_attacks(sq,7,occ);
}
static inline BB rook_attacks(int sq, BB occ) {
    return ray_attacks(sq,0,occ) | ray_attacks(sq,2,occ)
         | ray_attacks(sq,4,occ) | ray_attacks(sq,6,occ);
}
static inline BB queen_attacks(int sq, BB occ) {
    return bishop_attacks(sq,occ) | rook_attacks(sq,occ);
}

/* ================================================================
   SECTION 4: Zobrist hashing
   ================================================================ */

static uint64_t ZOB_PIECE[12][64];   /* [color*6+type][sq] */
static uint64_t ZOB_STM;             /* side to move */
static uint64_t ZOB_CASTLE[16];      /* castling rights */
static uint64_t ZOB_EP[8];           /* en passant file */

static uint64_t rng_state;
static uint64_t rng64(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}

static void init_zobrist(void) {
    rng_state = 0xCAFEBABE19970ULL ^ 0x1997ULL;
    for (int p=0;p<12;p++) for (int s=0;s<64;s++) ZOB_PIECE[p][s]=rng64();
    ZOB_STM = rng64();
    for (int i=0;i<16;i++) ZOB_CASTLE[i]=rng64();
    for (int i=0;i<8;i++)  ZOB_EP[i]=rng64();
}

/* ================================================================
   SECTION 5: Board representation
   ================================================================ */

typedef struct {
    BB   bb[2][6];    /* bb[color][piece_type] */
    BB   occ[3];      /* occ[WHITE], occ[BLACK], occ[BOTH] */
    int8_t sq[64];    /* piece type at each square (EMPTY=6 if none) */
    int8_t sqc[64];   /* color at each square (only valid if sq[s]!=EMPTY) */
    int  stm;         /* side to move */
    int  ep;          /* en passant square (NO_SQ if none) */
    int  cr;          /* castling rights */
    int  hmc;         /* halfmove clock */
    int  fmn;         /* fullmove number */
    uint64_t key;     /* Zobrist key */
} Board;

typedef struct {
    int8_t  cap_type;   /* captured piece type (EMPTY=none) */
    int8_t  cap_color;
    int8_t  piece_type; /* piece that was moved (saved for reliable undo) */
    int     ep;
    int     cr;
    int     hmc;
    uint64_t key;
} Undo;

static void board_clear(Board *b) {
    memset(b, 0, sizeof(*b));
    memset(b->sq, EMPTY, sizeof(b->sq));
    b->ep = NO_SQ;
}

static void put_piece(Board *b, int color, int pt, int sq) {
    if (pt < 0 || pt > 5 || color < 0 || color > 1 || sq < 0 || sq > 63) return;
    BB s = sq_bb(sq);
    b->bb[color][pt] |= s;
    b->occ[color]    |= s;
    b->occ[BOTH]     |= s;
    b->sq[sq]  = pt;
    b->sqc[sq] = color;
    b->key ^= ZOB_PIECE[color*6+pt][sq];
}

static void remove_piece(Board *b, int color, int pt, int sq) {
    if (pt < 0 || pt > 5 || color < 0 || color > 1 || sq < 0 || sq > 63) return;
    BB s = sq_bb(sq);
    b->bb[color][pt] &= ~s;
    b->occ[color]    &= ~s;
    b->occ[BOTH]     &= ~s;
    b->sq[sq]  = EMPTY;
    b->key ^= ZOB_PIECE[color*6+pt][sq];
}

static void move_piece(Board *b, int color, int pt, int from, int to) {
    remove_piece(b, color, pt, from);
    put_piece(b, color, pt, to);
}

/* Parse FEN string into Board */
static bool board_from_fen(Board *b, const char *fen) {
    board_clear(b);
    const char *p = fen;

    /* Piece placement */
    int rank=7, file=0;
    while (*p && *p != ' ') {
        if (*p == '/') { rank--; file=0; }
        else if (*p>='1'&&*p<='8') { file+=*p-'0'; }
        else {
            int color = islower(*p) ? BLACK : WHITE;
            char c = tolower(*p);
            int pt;
            switch(c) {
                case 'p': pt=PAWN;   break;
                case 'n': pt=KNIGHT; break;
                case 'b': pt=BISHOP; break;
                case 'r': pt=ROOK;   break;
                case 'q': pt=QUEEN;  break;
                case 'k': pt=KING;   break;
                default: return false;
            }
            put_piece(b, color, pt, SQ(file, rank));
            file++;
        }
        p++;
    }
    if (*p==' ') p++;

    /* Side to move */
    b->stm = (*p=='w') ? WHITE : BLACK;
    if (b->stm==BLACK) b->key ^= ZOB_STM;
    if (*p) p++;
    if (*p==' ') p++;

    /* Castling rights */
    b->cr = 0;
    while (*p && *p!=' ') {
        switch(*p) {
            case 'K': b->cr|=CASTLE_WK; break;
            case 'Q': b->cr|=CASTLE_WQ; break;
            case 'k': b->cr|=CASTLE_BK; break;
            case 'q': b->cr|=CASTLE_BQ; break;
        }
        p++;
    }
    b->key ^= ZOB_CASTLE[b->cr];
    if (*p==' ') p++;

    /* En passant */
    if (*p && *p!='-') {
        int f = p[0]-'a';
        int r = p[1]-'1';
        b->ep = SQ(f,r);
        b->key ^= ZOB_EP[f];
        p+=2;
    } else { if (*p=='-') p++; }
    if (*p==' ') p++;

    /* Halfmove clock */
    b->hmc = atoi(p);
    while (*p && *p!=' ') p++;
    if (*p==' ') p++;

    /* Fullmove number */
    b->fmn = atoi(p);
    return true;
}

/* ================================================================
   SECTION 6: Is-attacked and make/unmake move
   ================================================================ */

static bool is_attacked(const Board *b, int sq, int by) {
    BB occ = b->occ[BOTH];
    if (PAWN_ATK[by^1][sq] & b->bb[by][PAWN])   return true;
    if (KNIGHT_ATK[sq]     & b->bb[by][KNIGHT])  return true;
    if (KING_ATK[sq]       & b->bb[by][KING])    return true;
    if (bishop_attacks(sq,occ) & (b->bb[by][BISHOP]|b->bb[by][QUEEN])) return true;
    if (rook_attacks(sq,occ)   & (b->bb[by][ROOK]  |b->bb[by][QUEEN])) return true;
    return false;
}

/* Castling rights mask: when a piece moves from/to these squares, revoke rights */
static const int CASTLE_MASK[64] = {
    [0]  = ~CASTLE_WQ, [7]  = ~CASTLE_WK,
    [56] = ~CASTLE_BQ, [63] = ~CASTLE_BK,
    [4]  = ~(CASTLE_WK|CASTLE_WQ),
    [60] = ~(CASTLE_BK|CASTLE_BQ),
};
static inline int castle_mask(int sq) {
    if (sq==0)  return ~CASTLE_WQ;
    if (sq==7)  return ~CASTLE_WK;
    if (sq==4)  return ~(CASTLE_WK|CASTLE_WQ);
    if (sq==56) return ~CASTLE_BQ;
    if (sq==63) return ~CASTLE_BK;
    if (sq==60) return ~(CASTLE_BK|CASTLE_BQ);
    return ~0;
}

static void do_move(Board *b, Move m, Undo *u) {
    int from = M_FROM(m), to = M_TO(m), flags = M_FLAGS(m);
    int us = b->stm, them = us^1;

    /* Save undo info */
    u->ep      = b->ep;
    u->cr      = b->cr;
    u->hmc     = b->hmc;
    u->key     = b->key;
    u->cap_type  = EMPTY;
    u->cap_color = them;

    /* Update Zobrist for old state */
    b->key ^= ZOB_STM;
    b->key ^= ZOB_CASTLE[b->cr];
    if (b->ep != NO_SQ) b->key ^= ZOB_EP[FILE_OF(b->ep)];

    int pt = b->sq[from];
    u->piece_type = pt;

    /* Handle capture */
    if (IS_CAP(m) && !IS_EP(m)) {
        int cap_pt = b->sq[to];
        u->cap_type = cap_pt;
        remove_piece(b, them, cap_pt, to);
    }

    /* Move the piece */
    if (IS_PROM(m)) {
        remove_piece(b, us, PAWN, from);
        put_piece(b, us, PROM_PT(m), to);
    } else {
        move_piece(b, us, pt, from, to);
    }

    /* En passant capture */
    if (IS_EP(m)) {
        int cap_sq = (us==WHITE) ? to-8 : to+8;
        u->cap_type  = PAWN;
        u->cap_color = them;
        remove_piece(b, them, PAWN, cap_sq);
    }

    /* Castling: move rook */
    if (flags==FL_CKS) {
        int rook_from = (us==WHITE) ? 7  : 63;
        int rook_to   = (us==WHITE) ? 5  : 61;
        move_piece(b, us, ROOK, rook_from, rook_to);
    } else if (flags==FL_CQS) {
        int rook_from = (us==WHITE) ? 0  : 56;
        int rook_to   = (us==WHITE) ? 3  : 59;
        move_piece(b, us, ROOK, rook_from, rook_to);
    }

    /* Update en passant */
    b->ep = NO_SQ;
    if (flags==FL_DPUSH) {
        b->ep = (us==WHITE) ? from+8 : from-8;
        b->key ^= ZOB_EP[FILE_OF(b->ep)];
    }

    /* Update castling rights */
    b->cr &= castle_mask(from) & castle_mask(to);
    b->key ^= ZOB_CASTLE[b->cr];

    /* Halfmove clock */
    b->hmc = (IS_CAP(m) || pt==PAWN) ? 0 : b->hmc+1;

    /* Fullmove number */
    if (us==BLACK) b->fmn++;

    b->stm = them;
}

static void undo_move(Board *b, Move m, const Undo *u) {
    int from = M_FROM(m), to = M_TO(m), flags = M_FLAGS(m);
    int them = b->stm, us = them^1;  /* we just flipped stm in do_move */

    b->stm = us;
    b->ep  = u->ep;
    b->cr  = u->cr;
    b->hmc = u->hmc;
    if (us==BLACK) b->fmn--;
    b->key = u->key;

    /* Undo castling rook */
    if (flags==FL_CKS) {
        int rook_from = (us==WHITE) ? 7  : 63;
        int rook_to   = (us==WHITE) ? 5  : 61;
        move_piece(b, us, ROOK, rook_to, rook_from);
    } else if (flags==FL_CQS) {
        int rook_from = (us==WHITE) ? 0  : 56;
        int rook_to   = (us==WHITE) ? 3  : 59;
        move_piece(b, us, ROOK, rook_to, rook_from);
    }

    /* Undo promotion */
    if (IS_PROM(m)) {
        remove_piece(b, us, PROM_PT(m), to);
        put_piece(b, us, PAWN, from);
    } else {
        move_piece(b, us, u->piece_type, to, from);
    }

    /* Restore capture */
    if (IS_EP(m)) {
        int cap_sq = (us==WHITE) ? to-8 : to+8;
        put_piece(b, them, PAWN, cap_sq);
    } else if (u->cap_type != EMPTY) {
        put_piece(b, them, u->cap_type, to);
    }
}

/* ================================================================
   SECTION 7: Move generation
   ================================================================ */

typedef struct { Move moves[MAX_MOVES]; int count; } MoveList;

static inline void add_move(MoveList *ml, Move m) {
    ml->moves[ml->count++] = m;
}

/* Add all quiet moves from 'from' to each set bit in 'targets' */
static void add_quiet_moves(MoveList *ml, int from, BB targets) {
    while (targets) { int to = pop_lsb(&targets); add_move(ml, MK_MOVE(from,to,FL_QUIET)); }
}
static void add_cap_moves(MoveList *ml, int from, BB targets) {
    while (targets) { int to = pop_lsb(&targets); add_move(ml, MK_MOVE(from,to,FL_CAP)); }
}

static void gen_pawn_moves(Board *b, MoveList *ml) {
    int us = b->stm, them = us^1;
    BB pawns = b->bb[us][PAWN];
    BB occ   = b->occ[BOTH];
    BB empty = ~occ;
    BB theirs= b->occ[them] & ~b->bb[them][KING];

    if (us==WHITE) {
        BB push1 = (pawns << 8) & empty;
        BB push2 = ((push1 & (RANK_1<<16)) << 8) & empty;  /* rank 3 */
        BB capL  = ((pawns & ~FILE_A) << 7) & theirs;
        BB capR  = ((pawns & ~(FILE_A<<7)) << 9) & theirs;

        /* Promotions (from rank 7) */
        BB prom1 = push1 & RANK_8;
        BB prom_capL = capL & RANK_8;
        BB prom_capR = capR & RANK_8;
        push1 &= ~RANK_8; capL &= ~RANK_8; capR &= ~RANK_8;

        while (push1) { int to=pop_lsb(&push1);   add_move(ml,MK_MOVE(to-8,to,FL_QUIET)); }
        while (push2) { int to=pop_lsb(&push2);   add_move(ml,MK_MOVE(to-16,to,FL_DPUSH)); }
        while (capL)  { int to=pop_lsb(&capL);    add_move(ml,MK_MOVE(to-7,to,FL_CAP)); }
        while (capR)  { int to=pop_lsb(&capR);    add_move(ml,MK_MOVE(to-9,to,FL_CAP)); }

        /* Promotions */
        int pfl[4] = {FL_QPROM,FL_RPROM,FL_BPROM,FL_NPROM};
        int cfl[4] = {FL_QPROMC,FL_RPROMC,FL_BPROMC,FL_NPROMC};
        { BB pm=prom1;     while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to-8,to,pfl[i])); } }
        { BB pm=prom_capL; while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to-7,to,cfl[i])); } }
        { BB pm=prom_capR; while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to-9,to,cfl[i])); } }

        /* En passant */
        if (b->ep != NO_SQ) {
            BB ep_bb = sq_bb(b->ep);
            if ((pawns & ~FILE_A) && ((pawns & ~FILE_A) << 7) & ep_bb)
                add_move(ml, MK_MOVE(b->ep-7, b->ep, FL_EP));
            if ((pawns & ~(FILE_A<<7)) && ((pawns & ~(FILE_A<<7)) << 9) & ep_bb)
                add_move(ml, MK_MOVE(b->ep-9, b->ep, FL_EP));
        }
    } else {
        BB push1 = (pawns >> 8) & empty;
        BB push2 = ((push1 & (RANK_8>>16)) >> 8) & empty;  /* rank 6 */
        BB capL  = ((pawns & ~FILE_A) >> 9) & theirs;
        BB capR  = ((pawns & ~(FILE_A<<7)) >> 7) & theirs;

        BB prom1 = push1 & RANK_1;
        BB prom_capL = capL & RANK_1;
        BB prom_capR = capR & RANK_1;
        push1 &= ~RANK_1; capL &= ~RANK_1; capR &= ~RANK_1;

        while (push1) { int to=pop_lsb(&push1);  add_move(ml,MK_MOVE(to+8,to,FL_QUIET)); }
        while (push2) { int to=pop_lsb(&push2);  add_move(ml,MK_MOVE(to+16,to,FL_DPUSH)); }
        while (capL)  { int to=pop_lsb(&capL);   add_move(ml,MK_MOVE(to+9,to,FL_CAP)); }
        while (capR)  { int to=pop_lsb(&capR);   add_move(ml,MK_MOVE(to+7,to,FL_CAP)); }

        int pfl[4] = {FL_QPROM,FL_RPROM,FL_BPROM,FL_NPROM};
        int cfl[4] = {FL_QPROMC,FL_RPROMC,FL_BPROMC,FL_NPROMC};
        { BB pm=prom1;     while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to+8,to,pfl[i])); } }
        { BB pm=prom_capL; while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to+9,to,cfl[i])); } }
        { BB pm=prom_capR; while(pm){ int to=pop_lsb(&pm); for(int i=0;i<4;i++) add_move(ml,MK_MOVE(to+7,to,cfl[i])); } }

        if (b->ep != NO_SQ) {
            BB ep_bb = sq_bb(b->ep);
            if ((pawns & ~FILE_A) && ((pawns & ~FILE_A) >> 9) & ep_bb)
                add_move(ml, MK_MOVE(b->ep+9, b->ep, FL_EP));
            if ((pawns & ~(FILE_A<<7)) && ((pawns & ~(FILE_A<<7)) >> 7) & ep_bb)
                add_move(ml, MK_MOVE(b->ep+7, b->ep, FL_EP));
        }
    }
}

static void gen_piece_moves(Board *b, MoveList *ml) {
    int us = b->stm;
    BB occ   = b->occ[BOTH];
    BB ours  = b->occ[us];
    BB theirs= b->occ[us^1] & ~b->bb[us^1][KING];
    BB empty = ~occ;

    /* Knights */
    BB knights = b->bb[us][KNIGHT];
    while (knights) {
        int sq = pop_lsb(&knights);
        BB atk = KNIGHT_ATK[sq] & ~ours;
        add_quiet_moves(ml, sq, atk & empty);
        add_cap_moves(ml, sq, atk & theirs);
    }

    /* Bishops */
    BB bishops = b->bb[us][BISHOP];
    while (bishops) {
        int sq = pop_lsb(&bishops);
        BB atk = bishop_attacks(sq, occ) & ~ours;
        add_quiet_moves(ml, sq, atk & empty);
        add_cap_moves(ml, sq, atk & theirs);
    }

    /* Rooks */
    BB rooks = b->bb[us][ROOK];
    while (rooks) {
        int sq = pop_lsb(&rooks);
        BB atk = rook_attacks(sq, occ) & ~ours;
        add_quiet_moves(ml, sq, atk & empty);
        add_cap_moves(ml, sq, atk & theirs);
    }

    /* Queens */
    BB queens = b->bb[us][QUEEN];
    while (queens) {
        int sq = pop_lsb(&queens);
        BB atk = queen_attacks(sq, occ) & ~ours;
        add_quiet_moves(ml, sq, atk & empty);
        add_cap_moves(ml, sq, atk & theirs);
    }

    /* King */
    {
        int sq = LSB(b->bb[us][KING]);
        BB atk = KING_ATK[sq] & ~ours;
        add_quiet_moves(ml, sq, atk & empty);
        add_cap_moves(ml, sq, atk & theirs);
    }
}

static void gen_castling(Board *b, MoveList *ml) {
    int us = b->stm;
    BB occ = b->occ[BOTH];

    if (us==WHITE) {
        if ((b->cr & CASTLE_WK)
            && !(occ & 0x60ULL)  /* f1, g1 empty */
            && !is_attacked(b,4,BLACK) && !is_attacked(b,5,BLACK) && !is_attacked(b,6,BLACK))
            add_move(ml, MK_MOVE(4,6,FL_CKS));
        if ((b->cr & CASTLE_WQ)
            && !(occ & 0xEULL)   /* b1,c1,d1 empty */
            && !is_attacked(b,4,BLACK) && !is_attacked(b,3,BLACK) && !is_attacked(b,2,BLACK))
            add_move(ml, MK_MOVE(4,2,FL_CQS));
    } else {
        if ((b->cr & CASTLE_BK)
            && !(occ & 0x6000000000000000ULL)
            && !is_attacked(b,60,WHITE) && !is_attacked(b,61,WHITE) && !is_attacked(b,62,WHITE))
            add_move(ml, MK_MOVE(60,62,FL_CKS));
        if ((b->cr & CASTLE_BQ)
            && !(occ & 0x0E00000000000000ULL)
            && !is_attacked(b,60,WHITE) && !is_attacked(b,59,WHITE) && !is_attacked(b,58,WHITE))
            add_move(ml, MK_MOVE(60,58,FL_CQS));
    }
}

/* Generate pseudo-legal moves, then filter for legality */
static void gen_legal_moves(Board *b, MoveList *legal) {
    MoveList pseudo = {.count=0};
    gen_pawn_moves(b, &pseudo);
    gen_piece_moves(b, &pseudo);
    gen_castling(b, &pseudo);

    legal->count = 0;
    int us = b->stm;
    for (int i=0; i<pseudo.count; i++) {
        Move m = pseudo.moves[i];
        Undo u;
        do_move(b, m, &u);
        int king_sq = LSB(b->bb[us][KING]);
        if (!is_attacked(b, king_sq, b->stm))  /* stm flipped, so stm is 'them' now */
            legal->moves[legal->count++] = m;
        undo_move(b, m, &u);
    }
}

static bool in_check(Board *b) {
    int king_sq = LSB(b->bb[b->stm][KING]);
    return is_attacked(b, king_sq, b->stm^1);
}

/* ================================================================
   SECTION 8: Static evaluation (mirrors evaluation.py)
   ================================================================ */

static int pst_score(int pt, int sq, int color, double phase) {
    /* Mirror square for black: rank flip */
    int idx = (color==WHITE) ? sq : (sq^56);
    int mg, eg;
    switch(pt) {
        case PAWN:   mg=PST_PAWN_MG[idx]; eg=PST_PAWN_EG[idx]; break;
        case KNIGHT: mg=PST_KNIGHT[idx];  eg=PST_KNIGHT[idx];  break;
        case BISHOP: mg=PST_BISHOP[idx];  eg=PST_BISHOP[idx];  break;
        case ROOK:   mg=PST_ROOK_MG[idx]; eg=PST_ROOK_MG[idx]; break;
        case QUEEN:  mg=PST_QUEEN_MG[idx];eg=PST_QUEEN_MG[idx];break;
        case KING:   mg=PST_KING_MG[idx]; eg=PST_KING_EG[idx]; break;
        default: return 0;
    }
    return (int)(mg*(1.0-phase) + eg*phase);
}

static double get_phase(const Board *b) {
    int phase = POPCOUNT(b->bb[WHITE][KNIGHT]) + POPCOUNT(b->bb[BLACK][KNIGHT])
              + POPCOUNT(b->bb[WHITE][BISHOP]) + POPCOUNT(b->bb[BLACK][BISHOP])
              + (POPCOUNT(b->bb[WHITE][ROOK])  + POPCOUNT(b->bb[BLACK][ROOK]))  * 2
              + (POPCOUNT(b->bb[WHITE][QUEEN]) + POPCOUNT(b->bb[BLACK][QUEEN])) * 4;
    if (phase > 24) phase = 24;
    return 1.0 - (double)phase / 24.0;
}

static int pawn_structure_score(const Board *b, int color) {
    int score = 0;
    BB pawns      = b->bb[color][PAWN];
    BB opp_pawns  = b->bb[color^1][PAWN];
    BB pawns_copy = pawns;

    while (pawns_copy) {
        int sq = pop_lsb(&pawns_copy);
        int f  = FILE_OF(sq);
        int r  = RANK_OF(sq);

        /* Doubled pawns */
        if (POPCOUNT(b->bb[color][PAWN] & (FILE_A << f)) > 1)
            score -= 20;

        /* Isolated pawns */
        BB adj_files = 0;
        if (f>0) adj_files |= (FILE_A << (f-1));
        if (f<7) adj_files |= (FILE_A << (f+1));
        if (!(pawns & adj_files))
            score -= 30;

        /* Passed pawns */
        BB ahead_mask = 0;
        BB block_files = 0;
        if (f>0) block_files |= (FILE_A << (f-1));
        block_files |= (FILE_A << f);
        if (f<7) block_files |= (FILE_A << (f+1));

        if (color==WHITE) {
            for (int rr=r+1; rr<8; rr++) ahead_mask |= (0xFFULL << (rr*8));
        } else {
            for (int rr=0; rr<r; rr++) ahead_mask |= (0xFFULL << (rr*8));
        }
        if (!(opp_pawns & block_files & ahead_mask)) {
            int advance = (color==WHITE) ? r : (7-r);
            static const int PASSED_BONUS[8] = {0,10,20,40,60,80,120,0};
            score += PASSED_BONUS[advance];
        }
    }
    return score;
}

static int bishop_pair_score(const Board *b, int color) {
    BB bishops = b->bb[color][BISHOP];
    if (POPCOUNT(bishops) < 2) return 0;
    /* Check light and dark squares */
    bool light=false, dark=false;
    BB bc = bishops;
    while (bc) {
        int sq = pop_lsb(&bc);
        if ((FILE_OF(sq)+RANK_OF(sq))%2==1) light=true; else dark=true;
    }
    return (light&&dark) ? 50 : 0;
}

static int rook_bonus_score(const Board *b, int color) {
    int score = 0;
    BB own_pawn_files = 0, opp_pawn_files = 0;
    BB op = b->bb[color][PAWN];
    while (op) { int s=pop_lsb(&op); own_pawn_files |= (FILE_A<<FILE_OF(s)); }
    op = b->bb[color^1][PAWN];
    while (op) { int s=pop_lsb(&op); opp_pawn_files |= (FILE_A<<FILE_OF(s)); }

    int seventh = (color==WHITE) ? 6 : 1;
    BB rooks = b->bb[color][ROOK];
    while (rooks) {
        int sq = pop_lsb(&rooks);
        if (RANK_OF(sq)==seventh) score += 25;
        BB fmask = FILE_A << FILE_OF(sq);
        if (!(own_pawn_files & fmask)) {
            score += (opp_pawn_files & fmask) ? 12 : 25;
        }
    }
    return score;
}

static int king_safety_score(const Board *b, int color, double phase) {
    int king_sq = LSB(b->bb[color][KING]);
    int score = 0;
    double mg_w = 1.0 - phase;

    /* Pawn shield */
    if (mg_w > 0.2) {
        BB shield = KING_ATK[king_sq] & b->bb[color][PAWN];
        score += (int)(POPCOUNT(shield) * 10 * mg_w);
    }

    /* Open files near king */
    int kf = FILE_OF(king_sq);
    for (int df=-1; df<=1; df++) {
        int f = kf+df;
        if (f<0||f>7) continue;
        if (!(b->bb[color][PAWN] & (FILE_A<<f)))
            score -= (int)(15 * mg_w);
    }

    /* Endgame centralization */
    if (phase > 0.4) {
        double dist = fabs(3.5-FILE_OF(king_sq)) + fabs(3.5-RANK_OF(king_sq));
        score += (int)((7.0-dist) * 5.0 * phase);
    }
    return score;
}

static int mobility_score(const Board *b, int color) {
    BB occ  = b->occ[BOTH];
    BB ours = b->occ[color];
    int score = 0;
    BB knights = b->bb[color][KNIGHT];
    while (knights) { int s=pop_lsb(&knights); score += POPCOUNT(KNIGHT_ATK[s] & ~ours)*2; }
    BB bishops = b->bb[color][BISHOP];
    while (bishops) { int s=pop_lsb(&bishops); score += POPCOUNT(bishop_attacks(s,occ) & ~ours)*2; }
    BB rooks = b->bb[color][ROOK];
    while (rooks) { int s=pop_lsb(&rooks); score += POPCOUNT(rook_attacks(s,occ) & ~ours)*2; }
    BB queens = b->bb[color][QUEEN];
    while (queens) { int s=pop_lsb(&queens); score += POPCOUNT(queen_attacks(s,occ) & ~ours)*2; }
    return score;
}

static int connected_rooks_score(const Board *b, int color) {
    BB rooks = b->bb[color][ROOK];
    if (POPCOUNT(rooks) < 2) return 0;
    BB rc = rooks;
    while (rc) {
        int s = pop_lsb(&rc);
        if (rook_attacks(s, b->occ[BOTH]) & rooks & ~sq_bb(s))
            return 20;
    }
    return 0;
}

static int knight_outpost_score(const Board *b, int color) {
    int score = 0;
    BB knights = b->bb[color][KNIGHT];
    BB opp_pawns = b->bb[color^1][PAWN];
    BB own_pawns = b->bb[color][PAWN];
    while (knights) {
        int sq = pop_lsb(&knights);
        int r = RANK_OF(sq);
        int adv = (color==WHITE) ? r : (7-r);
        if (adv < 3) continue;  /* not advanced enough */
        /* Not attackable by enemy pawn */
        if (PAWN_ATK[color^1][sq] & opp_pawns) continue;
        /* Supported by own pawn */
        if (PAWN_ATK[color][sq] & own_pawns)
            score += 15 + adv * 3;
        else
            score += 5;
    }
    return score;
}

static int evaluate(const Board *b) {
    /* Terminal checks */
    if (!b->bb[WHITE][KING] || !b->bb[BLACK][KING]) return 0; /* safety */

    double phase = get_phase(b);
    int score = 0;

    for (int color=0; color<2; color++) {
        int sign = (color==WHITE) ? 1 : -1;
        int s = 0;

        /* Material + PST */
        for (int pt=0; pt<6; pt++) {
            BB pieces = b->bb[color][pt];
            while (pieces) {
                int sq = pop_lsb(&pieces);
                s += MAT[pt];
                s += pst_score(pt, sq, color, phase);
            }
        }

        s += pawn_structure_score(b, color);
        s += bishop_pair_score(b, color);
        s += rook_bonus_score(b, color);
        s += connected_rooks_score(b, color);
        s += king_safety_score(b, color, phase);
        s += mobility_score(b, color);
        s += knight_outpost_score(b, color);

        score += sign * s;
    }
    /* Tempo bonus: small bonus for side to move */
    score += (b->stm == WHITE) ? 10 : -10;
    return score;
}

/* ================================================================
   SECTION 9: Static Exchange Evaluation (SEE)
   ================================================================ */

/* Fast SEE using bitboard attacker sets — no move generation needed */
static BB all_attackers(const Board *b, int sq, BB occ) {
    return (PAWN_ATK[BLACK][sq] & b->bb[WHITE][PAWN])
         | (PAWN_ATK[WHITE][sq] & b->bb[BLACK][PAWN])
         | (KNIGHT_ATK[sq] & (b->bb[WHITE][KNIGHT] | b->bb[BLACK][KNIGHT]))
         | (KING_ATK[sq]   & (b->bb[WHITE][KING]   | b->bb[BLACK][KING]))
         | (bishop_attacks(sq,occ) & (b->bb[WHITE][BISHOP]|b->bb[BLACK][BISHOP]
                                     |b->bb[WHITE][QUEEN] |b->bb[BLACK][QUEEN]))
         | (rook_attacks(sq,occ)   & (b->bb[WHITE][ROOK]  |b->bb[BLACK][ROOK]
                                     |b->bb[WHITE][QUEEN] |b->bb[BLACK][QUEEN]));
}

static int see(const Board *b, Move m) {
    if (IS_EP(m)) return 0;
    int to   = M_TO(m);
    int from = M_FROM(m);
    int cap_pt = b->sq[to];
    if (cap_pt == EMPTY) return 0;

    int gain[32];
    int depth = 0;
    gain[0] = MAT[cap_pt];

    BB occ      = b->occ[BOTH] ^ sq_bb(from);  /* remove the moving piece */
    BB attackers = all_attackers(b, to, occ);
    int side = b->stm ^ 1;  /* side to recapture */
    int last_pt  = b->sq[from];

    while (1) {
        depth++;
        gain[depth] = MAT[last_pt] - gain[depth-1];
        if (gain[depth] < 0 && gain[depth-1] < 0) break;

        /* Find LVA for 'side' */
        int lva_pt = -1;
        int lva_sq = -1;
        for (int pt = PAWN; pt <= KING; pt++) {
            BB candidates = attackers & b->bb[side][pt];
            if (candidates) {
                lva_pt = pt;
                lva_sq = LSB(candidates);
                break;
            }
        }
        if (lva_pt < 0) break;

        occ      ^= sq_bb(lva_sq);   /* remove this attacker */
        attackers = all_attackers(b, to, occ);
        side    ^= 1;
        last_pt  = lva_pt;
        if (depth >= 30) break;
    }

    /* Negamax backpropagation */
    for (int i = depth-1; i > 0; i--)
        gain[i-1] = (gain[i-1] > -gain[i]) ? gain[i-1] : -gain[i];

    return gain[0];
}

/* ================================================================
   SECTION 10: Transposition Table
   ================================================================ */

typedef struct {
    uint64_t key;
    int32_t  score;
    int8_t   depth;
    uint8_t  flag;
    Move     best_move;
} TTEntry;

#define TT_SIZE (1<<21)  /* 2M entries */
static TTEntry tt[TT_SIZE];

static void tt_clear(void) { memset(tt, 0, sizeof(tt)); }

static TTEntry* tt_probe(uint64_t key) {
    return &tt[key & (TT_SIZE-1)];
}

static void tt_store(uint64_t key, int depth, int score, int flag, Move bm) {
    TTEntry *e = &tt[key & (TT_SIZE-1)];
    e->key   = key;
    e->score = score;
    e->depth = (int8_t)depth;
    e->flag  = (uint8_t)flag;
    e->best_move = bm;
}

/* Forward declarations for game history (defined in SECTION 12) */
extern uint64_t g_game_keys[1024];
extern int g_game_ply;

/* ================================================================
   SECTION 11: Search
   ================================================================ */

typedef struct {
    Move killers[MAX_PLY][2];
    int  history[2][64][64];
    long nodes;
    int64_t start_ms;
    int     time_limit_ms;
    bool    stop;
    int     root_depth;
    uint64_t key_stack[MAX_PLY * 2]; /* position history for repetition detection */
    int      key_sp;                 /* stack pointer */
} Search;

static Search S;

static inline bool time_up(void) {
    if ((S.nodes & 0xFFF) == 0)
        if (get_time_ms() - S.start_ms > S.time_limit_ms)
            S.stop = true;
    return S.stop;
}

/* Move ordering score */
static int move_score(const Board *b, Move m, int ply, Move pv_move) {
    if (m == pv_move) return 2000000;

    if (IS_CAP(m)) {
        int sv = see(b, m);
        if (sv > 0) return 1100000 + sv;
        if (sv == 0) return 1000000;
        return 200000 + sv;
    }
    if (IS_PROM(m)) return 900000 + MAT[PROM_PT(m)];

    /* Killer heuristic */
    if (ply < MAX_PLY) {
        if (m == S.killers[ply][0]) return 800000;
        if (m == S.killers[ply][1]) return 799999;
    }

    /* History heuristic */
    return S.history[b->stm][M_FROM(m)][M_TO(m)];
}

static void sort_moves(const Board *b, MoveList *ml, int ply, Move pv_move) {
    int scores[MAX_MOVES];
    for (int i=0; i<ml->count; i++)
        scores[i] = move_score(b, ml->moves[i], ply, pv_move);
    /* Insertion sort (small N, cache friendly) */
    for (int i=1; i<ml->count; i++) {
        Move tm = ml->moves[i]; int ts = scores[i];
        int j=i-1;
        while (j>=0 && scores[j]<ts) { ml->moves[j+1]=ml->moves[j]; scores[j+1]=scores[j]; j--; }
        ml->moves[j+1]=tm; scores[j+1]=ts;
    }
}

static int quiescence(Board *b, int alpha, int beta) {
    S.nodes++;
    if (time_up()) return 0;

    bool in_chk = in_check(b);
    int stand_pat = 0;

    if (!in_chk) {
        int raw = evaluate(b);
        stand_pat = (b->stm==WHITE) ? raw : -raw;
        if (stand_pat >= beta) return stand_pat;
        if (stand_pat > alpha) alpha = stand_pat;
    }

    int best = in_chk ? -INF : stand_pat;

    /* Generate: all moves when in check, else captures+promotions */
    MoveList ml; ml.count=0;
    gen_pawn_moves(b, &ml);
    gen_piece_moves(b, &ml);
    if (in_chk) gen_castling(b, &ml);

    /* Collect legal candidates */
    MoveList cands; cands.count=0;
    int us = b->stm;
    for (int i=0; i<ml.count; i++) {
        Move m = ml.moves[i];
        if (!in_chk && !IS_CAP(m) && !IS_PROM(m)) continue;
        Undo u; do_move(b, m, &u);
        if (!is_attacked(b, LSB(b->bb[us][KING]), b->stm))
            cands.moves[cands.count++] = m;
        undo_move(b, m, &u);
    }

    if (in_chk && cands.count == 0) return -(MATE_SCORE - 100);  /* checkmate */

    sort_moves(b, &cands, 0, MOVE_NONE);

    for (int i=0; i<cands.count; i++) {
        Move m = cands.moves[i];
        if (!in_chk) {
            if (!IS_PROM(m) && see(b,m)<0) continue;
            if (!IS_PROM(m)) {
                int to = M_TO(m);
                int victim_pt = b->sq[to];
                if (victim_pt != EMPTY && stand_pat + MAT[victim_pt] + 200 <= alpha) continue;
            }
        }
        Undo u; do_move(b, m, &u);
        int score = -quiescence(b, -beta, -alpha);
        undo_move(b, m, &u);
        if (score > best) best = score;
        if (score > alpha) alpha = score;
        if (alpha >= beta) return best;
    }
    return best;
}

static int count_major(const Board *b, int color) {
    return POPCOUNT(b->bb[color][QUEEN])  + POPCOUNT(b->bb[color][ROOK])
         + POPCOUNT(b->bb[color][BISHOP]) + POPCOUNT(b->bb[color][KNIGHT]);
}

static int negamax(Board *b, int depth, int alpha, int beta, int ply) {
    S.nodes++;
    if (time_up()) return 0;

    /* Repetition / 50-move draw detection */
    if (ply > 0 && b->hmc >= 100) return 0;
    for (int i = 0; i < S.key_sp; i++)
        if (S.key_stack[i] == b->key) return 0;
    /* Check game history (positions before root) for 2-fold repetition */
    if (ply > 0) {
        for (int i = 0; i < g_game_ply - 1; i++)
            if (g_game_keys[i] == b->key) return 0;
    }

    /* TT probe */
    TTEntry *tte = tt_probe(b->key);
    Move pv_move = MOVE_NONE;
    if (tte->key == b->key) {
        pv_move = tte->best_move;
        if (tte->depth >= depth) {
            if (tte->flag == TT_EXACT) return tte->score;
            if (tte->flag == TT_LOWER && tte->score > alpha) alpha = tte->score;
            if (tte->flag == TT_UPPER && tte->score < beta)  beta  = tte->score;
            if (alpha >= beta) return tte->score;
        }
    }

    bool in_chk = in_check(b);

    if (depth <= 0) return quiescence(b, alpha, beta);

    /* Null move pruning */
    if (depth >= 3 && !in_chk && count_major(b, b->stm) >= 2) {
        int R = (depth >= 6) ? 3 : 2;
        Undo u;
        Move null_m = MK_MOVE(0,0,FL_QUIET);  /* null move placeholder */
        /* Manual null move (just flip side) */
        u.ep=b->ep; u.cr=b->cr; u.hmc=b->hmc; u.key=b->key;
        u.cap_type=EMPTY; u.cap_color=b->stm^1;
        b->key ^= ZOB_STM;
        if (b->ep!=NO_SQ) { b->key ^= ZOB_EP[FILE_OF(b->ep)]; b->ep=NO_SQ; }
        b->stm ^= 1;
        int null_score = -negamax(b, depth-1-R, -beta, -beta+1, ply+1);
        b->stm ^= 1;
        b->ep = u.ep; b->cr = u.cr; b->hmc = u.hmc; b->key = u.key;
        (void)null_m;
        if (null_score >= beta) return null_score;
    }

    /* Futility pruning */
    bool do_futility = false;
    int static_eval = 0;
    if ((depth==1||depth==2) && !in_chk) {
        static_eval = evaluate(b);
        if (b->stm==BLACK) static_eval = -static_eval;
        int margin = (depth==1) ? 100 : 300;
        if (static_eval + margin <= alpha) do_futility = true;
    }

    /* Generate moves */
    MoveList ml; ml.count=0;
    gen_pawn_moves(b, &ml);
    gen_piece_moves(b, &ml);
    gen_castling(b, &ml);

    /* Filter pseudo-legal */
    MoveList legal; legal.count=0;
    int us = b->stm;
    for (int i=0; i<ml.count; i++) {
        Move m = ml.moves[i];
        Undo u; do_move(b,m,&u);
        if (!is_attacked(b, LSB(b->bb[us][KING]), b->stm))
            legal.moves[legal.count++]=m;
        undo_move(b,m,&u);
    }

    if (legal.count==0) {
        return in_chk ? -(MATE_SCORE - ply) : 0;
    }

#ifdef FATHOM
    /* Syzygy WDL probe: perfect endgame play when pieces <= TB_LARGEST */
    if (g_tb_enabled && b->cr == 0) {
        int n_pieces = (int)__builtin_popcountll(b->occ[2]);
        if ((unsigned)n_pieces <= TB_LARGEST) {
            unsigned ep_sq = (b->ep == NO_SQ) ? 0 : (unsigned)b->ep;
            unsigned wdl = tb_probe_wdl(
                b->occ[WHITE], b->occ[BLACK],
                b->bb[WHITE][KING]   | b->bb[BLACK][KING],
                b->bb[WHITE][QUEEN]  | b->bb[BLACK][QUEEN],
                b->bb[WHITE][ROOK]   | b->bb[BLACK][ROOK],
                b->bb[WHITE][BISHOP] | b->bb[BLACK][BISHOP],
                b->bb[WHITE][KNIGHT] | b->bb[BLACK][KNIGHT],
                b->bb[WHITE][PAWN]   | b->bb[BLACK][PAWN],
                (unsigned)b->hmc, 0, ep_sq, b->stm == WHITE
            );
            if (wdl != TB_RESULT_FAILED) {
                int score = (wdl == TB_WIN)  ?  (MATE_SCORE - ply - 1) :
                            (wdl == TB_LOSS) ? -(MATE_SCORE - ply - 1) : 0;
                int flag  = (wdl == TB_WIN)  ? TT_LOWER :
                            (wdl == TB_LOSS) ? TT_UPPER : TT_EXACT;
                tt_store(b->key, 99, score, flag, MOVE_NONE);
                return score;
            }
        }
    }
#endif

    sort_moves(b, &legal, ply, pv_move);

    int best_score = -INF;
    Move best_move = MOVE_NONE;
    int orig_alpha = alpha;
    int moves_searched = 0;

    for (int i=0; i<legal.count; i++) {
        Move m = legal.moves[i];
        bool is_cap  = IS_CAP(m);
        bool is_prom = IS_PROM(m);

        /* Futility pruning: skip quiet non-check-giving late moves */
        if (do_futility && !is_cap && !is_prom && moves_searched > 0) {
            /* Check if it gives check quickly */
            Undo u; do_move(b,m,&u);
            bool gives_chk = in_check(b);
            undo_move(b,m,&u);
            if (!gives_chk) { moves_searched++; continue; }
        }

        uint64_t parent_key = b->key;
        Undo u; do_move(b,m,&u);
        S.key_stack[S.key_sp++] = parent_key;  /* push PARENT as ancestor */

        int score;
        int new_depth = depth - 1;
        if (depth >= 3 && moves_searched >= 4 && !is_cap && !is_prom && !in_chk) {
            /* LMR: reduced search, then full-depth if it fails high */
            int lmr_r = (int)fmax(1.0, sqrt((double)(depth-1)) * sqrt((double)moves_searched));
            int lmr_d = (int)fmax(1, new_depth-lmr_r);
            score = -negamax(b, lmr_d, -alpha-1, -alpha, ply+1);
            if (score > alpha)
                score = -negamax(b, new_depth, -beta, -alpha, ply+1);
        } else if (moves_searched==0) {
            score = -negamax(b, new_depth, -beta, -alpha, ply+1);
        } else {
            score = -negamax(b, new_depth, -alpha-1, -alpha, ply+1);
            if (score > alpha)
                score = -negamax(b, new_depth, -beta, -alpha, ply+1);
        }

        S.key_sp--;
        undo_move(b,m,&u);
        moves_searched++;

        if (score > best_score) { best_score=score; best_move=m; }
        if (score > alpha) alpha=score;
        if (alpha >= beta) {
            if (!is_cap) {
                /* Update killers */
                if (ply < MAX_PLY) {
                    if (S.killers[ply][0]!=m) { S.killers[ply][1]=S.killers[ply][0]; S.killers[ply][0]=m; }
                }
                S.history[us][M_FROM(m)][M_TO(m)] += depth*depth;
            }
            break;
        }
    }

    /* TT store */
    int flag = TT_EXACT;
    if (best_score <= orig_alpha) flag = TT_UPPER;
    else if (best_score >= beta)  flag = TT_LOWER;
    tt_store(b->key, depth, best_score, flag, best_move);

    return best_score;
}

/* Iterative deepening with aspiration windows */
static Move search_root(Board *b, int max_depth, int time_ms) {
    S.nodes     = 0;
    S.start_ms  = get_time_ms();
    S.time_limit_ms = time_ms;
    S.stop      = false;
    S.root_depth= 0;
    S.key_sp    = 0;
    memset(S.killers, 0, sizeof(S.killers));
    memset(S.history, 0, sizeof(S.history));

    Move best_move = MOVE_NONE;
    int  best_score = -INF;

    /* Generate root moves for sanity */
    MoveList legal; legal.count=0;
    {
        MoveList ml; ml.count=0;
        gen_pawn_moves(b,&ml); gen_piece_moves(b,&ml); gen_castling(b,&ml);
        int us=b->stm;
        for (int i=0;i<ml.count;i++) {
            Move m=ml.moves[i]; Undo u; do_move(b,m,&u);
            if (!is_attacked(b,LSB(b->bb[us][KING]),b->stm))
                legal.moves[legal.count++]=m;
            undo_move(b,m,&u);
        }
    }
    if (legal.count==0) return MOVE_NONE;
    if (legal.count==1) return legal.moves[0];

    for (int depth=1; depth<=max_depth; depth++) {
        if (get_time_ms()-S.start_ms > time_ms) break;

        int alpha, beta;
        if (depth >= 4 && best_score != -INF) {
            alpha = best_score - 50;
            beta  = best_score + 50;
        } else {
            alpha = -INF; beta = INF;
        }

        sort_moves(b, &legal, 0, best_move);

        int cur_best_score = -INF;
        Move cur_best_move = MOVE_NONE;
        bool full_window   = (alpha==-INF);

    retry:
        for (int i=0; i<legal.count; i++) {
            Move m = legal.moves[i];
            Undo u; do_move(b,m,&u);

            int score;
            if (i==0) {
                score = -negamax(b, depth-1, -beta, -alpha, 1);
            } else {
                score = -negamax(b, depth-1, -alpha-1, -alpha, 1);
                if (!S.stop && score>alpha)
                    score = -negamax(b, depth-1, -beta, -alpha, 1);
            }
            undo_move(b,m,&u);

            if (S.stop) goto done_depth;

            if (score > cur_best_score) { cur_best_score=score; cur_best_move=m; }
            if (score > alpha) alpha=score;
            if (alpha >= beta) break;
        }

        /* Aspiration window fail: re-search with full window */
        if (!full_window && (cur_best_score <= alpha-50 || cur_best_score >= beta+50)) {
            alpha=-INF; beta=INF; full_window=true;
            cur_best_score=-INF; cur_best_move=MOVE_NONE;
            goto retry;
        }

    done_depth:
        if (!S.stop && cur_best_move != MOVE_NONE) {
            best_move  = cur_best_move;
            best_score = cur_best_score;
        }

        S.root_depth = depth;

        /* UCI info output */
        int64_t elapsed = get_time_ms() - S.start_ms;
        int64_t nps = elapsed>0 ? S.nodes*1000/elapsed : 0;
        fprintf(stdout, "info depth %d score cp %d nodes %ld nps %ld time %lld\n",
                depth, best_score, S.nodes, (long)nps, (long long)elapsed);
        fflush(stdout);

        if (abs(best_score) >= MATE_THRESH) break;
    }
    return best_move;
}

/* ================================================================
   SECTION 12: UCI interface
   ================================================================ */

static Board g_board;
uint64_t g_game_keys[1024];  /* keys of positions seen this game */
int g_game_ply = 0;

static void uci_position(const char *line) {
    const char *p = line;
    if (strncmp(p,"position",8)!=0) return;
    p+=8;
    while (*p==' ') p++;

    if (strncmp(p,"startpos",8)==0) {
        board_from_fen(&g_board, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        p+=8;
    } else if (strncmp(p,"fen",3)==0) {
        p+=3;
        while (*p==' ') p++;
        board_from_fen(&g_board, p);
        /* Skip past the FEN (6 fields) */
        int fields=0;
        while (*p && fields<6) { while (*p&&*p!=' ')p++; if(*p==' '){p++;fields++;} }
    }

    /* Reset game history at start of position parsing */
    g_game_ply = 0;
    g_game_keys[g_game_ply++] = g_board.key;

    /* Apply moves */
    while (*p==' ') p++;
    if (strncmp(p,"moves",5)==0) {
        p+=5;
        while (*p) {
            while (*p==' ') p++;
            if (!*p) break;
            /* Parse move in UCI notation: e2e4, e7e8q, etc. */
            if (p[0]<'a'||p[0]>'h'||p[1]<'1'||p[1]>'8') break;
            int from = SQ(p[0]-'a', p[1]-'1');
            int to   = SQ(p[2]-'a', p[3]-'1');
            p+=4;
            int promo_pt = EMPTY;
            if (*p && *p!=' ') {
                switch(*p) {
                    case 'n': promo_pt=KNIGHT; break;
                    case 'b': promo_pt=BISHOP; break;
                    case 'r': promo_pt=ROOK;   break;
                    case 'q': promo_pt=QUEEN;  break;
                }
                if (promo_pt!=EMPTY) p++;
            }

            /* Find matching legal move */
            MoveList ml; ml.count=0;
            gen_pawn_moves(&g_board,&ml); gen_piece_moves(&g_board,&ml); gen_castling(&g_board,&ml);
            int us=g_board.stm;
            for (int i=0; i<ml.count; i++) {
                Move m=ml.moves[i];
                if (M_FROM(m)!=from||M_TO(m)!=to) continue;
                if (IS_PROM(m) && PROM_PT(m)!=promo_pt) continue;
                Undo u; do_move(&g_board,m,&u);
                if (!is_attacked(&g_board,LSB(g_board.bb[us][KING]),g_board.stm)) {
                    /* legal move applied — record position */
                    if (g_game_ply < 1024)
                        g_game_keys[g_game_ply++] = g_board.key;
                    break;
                }
                undo_move(&g_board,m,&u);
            }
        }
    }
}

static void print_move(Move best) {
    if (best == MOVE_NONE) {
        fprintf(stdout, "bestmove (none)\n");
        fflush(stdout);
        return;
    }
    int from=M_FROM(best), to=M_TO(best);
    char promo_char = 0;
    if (IS_PROM(best)) promo_char = "nbrq"[PROM_PT(best)-1];
    if (promo_char)
        fprintf(stdout, "bestmove %c%c%c%c%c\n",
                'a'+FILE_OF(from),'1'+RANK_OF(from),
                'a'+FILE_OF(to),  '1'+RANK_OF(to), promo_char);
    else
        fprintf(stdout, "bestmove %c%c%c%c\n",
                'a'+FILE_OF(from),'1'+RANK_OF(from),
                'a'+FILE_OF(to),  '1'+RANK_OF(to));
    fflush(stdout);
}

static Move book_probe(void);  /* forward decl — defined in SECTION 13 */

static void uci_go(const char *line) {
    int wtime=0, btime=0, winc=0, binc=0, movetime=0, movestogo=0, depth=MAX_PLY;
    bool infinite=false;

    const char *p = line+2; /* skip "go" */
    while (*p) {
        while (*p==' ') p++;
        if      (strncmp(p,"wtime",5)==0)     { p+=5; wtime=atoi(p); }
        else if (strncmp(p,"btime",5)==0)     { p+=5; btime=atoi(p); }
        else if (strncmp(p,"winc",4)==0)      { p+=4; winc=atoi(p); }
        else if (strncmp(p,"binc",4)==0)      { p+=4; binc=atoi(p); }
        else if (strncmp(p,"movetime",8)==0)  { p+=8; movetime=atoi(p); }
        else if (strncmp(p,"movestogo",9)==0) { p+=9; movestogo=atoi(p); }
        else if (strncmp(p,"depth",5)==0)     { p+=5; depth=atoi(p); }
        else if (strncmp(p,"infinite",8)==0)  { infinite=true; p+=8; }
        else { while (*p&&*p!=' ') p++; }
    }

    /* Try opening book first */
    Move book_m = book_probe();
    if (book_m != MOVE_NONE) {
        print_move(book_m);
        return;
    }

    int time_ms;
    if (movetime > 0) {
        time_ms = movetime - 50;
    } else if (infinite || (wtime == 0 && btime == 0 && movetime == 0)) {
        time_ms = 3600000;
    } else {
        int our_time = (g_board.stm==WHITE) ? wtime : btime;
        int our_inc  = (g_board.stm==WHITE) ? winc  : binc;
        /* Estimate moves remaining; use movestogo if provided */
        int moves_left = (movestogo > 0) ? movestogo : 30;
        time_ms = our_time / (moves_left + 3) + (int)(our_inc * 0.8);
        /* Safety: never spend more than 60% of remaining time */
        int cap = our_time * 60 / 100;
        if (time_ms > cap) time_ms = cap;
        if (time_ms < 50)  time_ms = 50;
    }

    Move best = search_root(&g_board, depth, time_ms);
    print_move(best);
}

/* ================================================================
   SECTION 13: Polyglot opening book
   ================================================================ */

/* Polyglot piece index mapping:
   bp=0 br=1 bb=2 bn=3 bq=4 bk=5  wp=6 wr=7 wb=8 wn=9 wq=10 wk=11
   Our pt:  PAWN=0 KNIGHT=1 BISHOP=2 ROOK=3 QUEEN=4 KING=5          */
static const int POLY_PT[2][6] = {
    {6, 7, 8, 9, 10, 11},  /* WHITE: PAWN=6,KNIGHT=7,BISHOP=8,ROOK=9,QUEEN=10,KING=11 */
    {0, 1, 2, 3,  4,  5},  /* BLACK: PAWN=0,KNIGHT=1,BISHOP=2,ROOK=3,QUEEN=4, KING=5  */
};

static uint64_t poly_key(const Board *b) {
    uint64_t key = 0;
    for (int c = 0; c < 2; c++) {
        for (int pt = 0; pt < 6; pt++) {
            BB pieces = b->bb[c][pt];
            while (pieces) {
                int sq = pop_lsb(&pieces);
                key ^= POLY_RAND[64 * POLY_PT[c][pt] + sq];
            }
        }
    }
    if (b->cr & CASTLE_WK) key ^= POLY_RAND[768];
    if (b->cr & CASTLE_WQ) key ^= POLY_RAND[769];
    if (b->cr & CASTLE_BK) key ^= POLY_RAND[770];
    if (b->cr & CASTLE_BQ) key ^= POLY_RAND[771];
    /* EP only when a capture is actually possible */
    if (b->ep != NO_SQ) {
        BB ep_bb = sq_bb(b->ep);
        bool ep_ok = false;
        if (b->stm == WHITE)
            ep_ok = (((b->bb[WHITE][PAWN] & ~FILE_A)      << 7) & ep_bb) ||
                    (((b->bb[WHITE][PAWN] & ~(FILE_A<<7)) << 9) & ep_bb);
        else
            ep_ok = (((b->bb[BLACK][PAWN] & ~FILE_A)      >> 9) & ep_bb) ||
                    (((b->bb[BLACK][PAWN] & ~(FILE_A<<7)) >> 7) & ep_bb);
        if (ep_ok) key ^= POLY_RAND[772 + FILE_OF(b->ep)];
    }
    if (b->stm == WHITE) key ^= POLY_RAND[780];
    return key;
}

static FILE *g_book     = NULL;
static long  g_book_len = 0;
static bool  g_own_book = true;
static char  g_book_path[512] = "book.bin";

static void book_open(const char *path) {
    if (g_book) { fclose(g_book); g_book = NULL; g_book_len = 0; }
    g_book = fopen(path, "rb");
    if (!g_book) return;
    fseek(g_book, 0, SEEK_END);
    g_book_len = ftell(g_book) / 16;
    rewind(g_book);
}

static uint64_t read_be64(FILE *f) {
    unsigned char b[8];
    if (fread(b,1,8,f)!=8) return 0;
    return ((uint64_t)b[0]<<56)|((uint64_t)b[1]<<48)|((uint64_t)b[2]<<40)|
           ((uint64_t)b[3]<<32)|((uint64_t)b[4]<<24)|((uint64_t)b[5]<<16)|
           ((uint64_t)b[6]<< 8)|((uint64_t)b[7]);
}
static uint16_t read_be16(FILE *f) {
    unsigned char b[2];
    if (fread(b,1,2,f)!=2) return 0;
    return (uint16_t)(b[0]<<8|b[1]);
}

static Move poly_to_move(uint16_t pm) {
    int tf = (pm>>0)&7, tr = (pm>>3)&7;
    int ff = (pm>>6)&7, fr = (pm>>9)&7;
    int promo = (pm>>12)&7;  /* 0=none 1=N 2=B 3=R 4=Q */

    int from = SQ(ff,fr), to = SQ(tf,tr);
    MoveList ml; ml.count=0;
    gen_pawn_moves(&g_board,&ml);
    gen_piece_moves(&g_board,&ml);
    gen_castling(&g_board,&ml);

    int us = g_board.stm;
    for (int i=0; i<ml.count; i++) {
        Move m = ml.moves[i];
        if (M_FROM(m)!=from || M_TO(m)!=to) continue;
        if (promo>0 && (!IS_PROM(m) || PROM_PT(m)!=promo)) continue;
        if (promo==0 && IS_PROM(m)) continue;
        Undo u; do_move(&g_board,m,&u);
        bool legal = !is_attacked(&g_board, LSB(g_board.bb[us][KING]), g_board.stm);
        undo_move(&g_board,m,&u);
        if (legal) return m;
    }
    return MOVE_NONE;
}

static Move book_probe(void) {
    if (!g_own_book || !g_book || g_book_len==0) return MOVE_NONE;

    uint64_t key = poly_key(&g_board);

    /* Binary search for first entry with this key */
    long lo=0, hi=g_book_len-1, first=-1;
    while (lo<=hi) {
        long mid=(lo+hi)/2;
        fseek(g_book, mid*16, SEEK_SET);
        uint64_t k = read_be64(g_book);
        if (k==key)      { first=mid; hi=mid-1; }
        else if (k<key)    lo=mid+1;
        else               hi=mid-1;
    }
    if (first<0) return MOVE_NONE;

    /* Collect entries with this key, pick highest weight */
    uint16_t best_pm=0; uint16_t best_w=0;
    for (long i=first; i<g_book_len; i++) {
        fseek(g_book, i*16, SEEK_SET);
        uint64_t k  = read_be64(g_book);
        if (k!=key) break;
        uint16_t pm = read_be16(g_book);
        uint16_t wt = read_be16(g_book);
        if (wt>best_w) { best_w=wt; best_pm=pm; }
    }
    if (!best_pm) return MOVE_NONE;

    Move m = poly_to_move(best_pm);
    return m;
}

/* ================================================================
   SECTION 14: Perft (move generation correctness test)
   ================================================================ */

static long perft(Board *b, int depth) {
    if (depth == 0) return 1;
    MoveList legal; legal.count = 0;
    gen_legal_moves(b, &legal);
    if (depth == 1) return legal.count;
    long nodes = 0;
    for (int i = 0; i < legal.count; i++) {
        Undo u; do_move(b, legal.moves[i], &u);
        nodes += perft(b, depth - 1);
        undo_move(b, legal.moves[i], &u);
    }
    return nodes;
}

static void run_perft(int depth) {
    MoveList legal; legal.count = 0;
    gen_legal_moves(&g_board, &legal);
    long total = 0;
    for (int i = 0; i < legal.count; i++) {
        Move m = legal.moves[i];
        char buf[6];
        int from = M_FROM(m), to = M_TO(m);
        buf[0] = 'a' + FILE_OF(from); buf[1] = '1' + RANK_OF(from);
        buf[2] = 'a' + FILE_OF(to);   buf[3] = '1' + RANK_OF(to);
        int len = 4;
        if (IS_PROM(m)) buf[len++] = "nbrq"[PROM_PT(m)-1];
        buf[len] = 0;
        Undo u; do_move(&g_board, m, &u);
        long cnt = perft(&g_board, depth - 1);
        undo_move(&g_board, m, &u);
        fprintf(stdout, "%s: %ld\n", buf, cnt);
        total += cnt;
    }
    fprintf(stdout, "\nNodes searched: %ld\n", total);
    fflush(stdout);
}

/* ================================================================
   SECTION 15: Main entry point
   ================================================================ */

int main(void) {
    /* Initialization */
    init_tables();
    init_zobrist();
    tt_clear();
    board_from_fen(&g_board, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    book_open(g_book_path);

    /* Fix get_phase: recompute since we had a bug in the initializer */
    /* (already fixed above in the get_phase function) */

    char line[4096];
    while (fgets(line, sizeof(line), stdin)) {
        /* Strip newline */
        int len = strlen(line);
        while (len>0 && (line[len-1]=='\n'||line[len-1]=='\r')) line[--len]=0;

        if (strcmp(line,"uci")==0) {
            fprintf(stdout, "id name DeeperBlue-C\n");
            fprintf(stdout, "id author DeeperBlue\n");
            fprintf(stdout, "option name OwnBook type check default true\n");
            fprintf(stdout, "option name BookFile type string default book.bin\n");
#ifdef FATHOM
            fprintf(stdout, "option name SyzygyPath type string default <empty>\n");
#endif
            fprintf(stdout, "uciok\n");
            fflush(stdout);
        } else if (strncmp(line,"setoption",9)==0) {
            const char *p = line+9;
            while (*p==' ') p++;
            if (strncmp(p,"name",4)==0) {
                p+=4; while(*p==' ')p++;
                if (strncmp(p,"OwnBook",7)==0) {
                    p+=7; while(*p==' ')p++;
                    if (strncmp(p,"value",5)==0) {
                        p+=5; while(*p==' ')p++;
                        g_own_book = (strncmp(p,"true",4)==0);
                    }
                } else if (strncmp(p,"BookFile",8)==0) {
                    p+=8; while(*p==' ')p++;
                    if (strncmp(p,"value",5)==0) {
                        p+=5; while(*p==' ')p++;
                        strncpy(g_book_path, p, sizeof(g_book_path)-1);
                        int len=(int)strlen(g_book_path);
                        while(len>0&&(g_book_path[len-1]==' '||g_book_path[len-1]=='\r'||
                              g_book_path[len-1]=='\n')) g_book_path[--len]=0;
                        book_open(g_book_path);
                    }
#ifdef FATHOM
                } else if (strncmp(p,"SyzygyPath",10)==0) {
                    p+=10; while(*p==' ')p++;
                    if (strncmp(p,"value",5)==0) {
                        p+=5; while(*p==' ')p++;
                        char tb_path[512];
                        strncpy(tb_path, p, sizeof(tb_path)-1);
                        int len=(int)strlen(tb_path);
                        while(len>0&&(tb_path[len-1]==' '||tb_path[len-1]=='\r'||
                              tb_path[len-1]=='\n')) tb_path[--len]=0;
                        g_tb_enabled = tb_init(tb_path);
                        if (g_tb_enabled)
                            fprintf(stdout, "info string Syzygy tablebases loaded (%u pieces)\n", TB_LARGEST);
                        else
                            fprintf(stdout, "info string Syzygy tablebase load FAILED: %s\n", tb_path);
                        fflush(stdout);
                    }
#endif
                }
            }
        } else if (strcmp(line,"isready")==0) {
            fprintf(stdout, "readyok\n");
            fflush(stdout);
        } else if (strcmp(line,"ucinewgame")==0) {
            tt_clear();
            board_from_fen(&g_board, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
            g_game_ply = 0;
        } else if (strncmp(line,"position",8)==0) {
            uci_position(line);
        } else if (strncmp(line,"go",2)==0) {
            uci_go(line);
        } else if (strcmp(line,"stop")==0) {
            S.stop = true;
        } else if (strncmp(line,"perft",5)==0) {
            int d = atoi(line+6);
            if (d < 1) d = 1;
            run_perft(d);
        } else if (strcmp(line,"quit")==0) {
            break;
        }
    }
    return 0;
}
