/*
 * LLC access patterns with known behavior, for validating replacement
 * policies in gem5. Touches one byte per 64-byte line.
 *
 *   llc_patterns fit    <kb> <passes>
 *       Loops over an array that fits in the LLC. Every policy should hit
 *       after the first pass.
 *   llc_patterns thrash <kb> <passes>
 *       Loops over an array somewhat larger than the LLC. LRU misses on
 *       every access. OPT keeps part of the array, so a good policy hits
 *       on part of each pass.
 *   llc_patterns mix    <reuse_kb> <stream_kb> <passes>
 *       Alternates a pass over a reused array with a pass over a large
 *       stream that is never reused. A good policy keeps the reused array
 *       and lets the stream pass through.
 *
 * Prints a checksum so that the result can be compared across policies
 * (the replacement policy must not change program output).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE 64

static unsigned long
pass(volatile unsigned char *buf, size_t bytes)
{
    unsigned long sum = 0;
    for (size_t i = 0; i < bytes; i += LINE) {
        sum += buf[i];
        buf[i] = (unsigned char)(buf[i] + 1);
    }
    return sum;
}

static unsigned char *
alloc(size_t bytes)
{
    unsigned char *buf = malloc(bytes);
    if (!buf) {
        perror("malloc");
        exit(1);
    }
    for (size_t i = 0; i < bytes; i++)
        buf[i] = (unsigned char)i;
    return buf;
}

int
main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: %s fit|thrash <kb> <passes>\n"
                        "       %s mix <reuse_kb> <stream_kb> <passes>\n",
                argv[0], argv[0]);
        return 1;
    }
    unsigned long sum = 0;

    if (strcmp(argv[1], "mix") == 0) {
        if (argc < 5) {
            fprintf(stderr, "mix needs <reuse_kb> <stream_kb> <passes>\n");
            return 1;
        }
        size_t reuse = (size_t)atol(argv[2]) * 1024;
        size_t stream = (size_t)atol(argv[3]) * 1024;
        int passes = atoi(argv[4]);
        unsigned char *r = alloc(reuse);
        unsigned char *s = alloc(stream);
        for (int p = 0; p < passes; p++) {
            sum += pass(r, reuse);
            /* a different part of the stream each time: never reused */
            size_t chunk = stream / (size_t)passes;
            sum += pass(s + (size_t)p * chunk, chunk);
        }
    } else {
        size_t bytes = (size_t)atol(argv[2]) * 1024;
        int passes = atoi(argv[3]);
        unsigned char *buf = alloc(bytes);
        for (int p = 0; p < passes; p++)
            sum += pass(buf, bytes);
    }

    printf("checksum %lu\n", sum);
    return 0;
}
