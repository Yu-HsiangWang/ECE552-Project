/* Check directory listing under gem5 SE, the way omnetpp loads NED files:
 * chdir into the folder, glob("*"), stat each entry. Also try readdir. */
#include <dirent.h>
#include <glob.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    const char *dir = argc > 1 ? argv[1] : ".";
    DIR *d = opendir(dir);
    int n = 0;
    if (!d) {
        perror("opendir");
    } else {
        struct dirent *e;
        while ((e = readdir(d)) != NULL)
            n++;
        closedir(d);
    }
    printf("readdir: %d entries\n", n);

    if (chdir(dir) != 0) {
        perror("chdir");
        return 1;
    }
    glob_t g;
    int rc = glob("*", 0, NULL, &g);
    printf("glob rc=%d count=%zu\n", rc, rc == 0 ? g.gl_pathc : 0);
    for (size_t i = 0; rc == 0 && i < g.gl_pathc && i < 3; i++) {
        struct stat st;
        int s = stat(g.gl_pathv[i], &st);
        printf("  %s stat=%d dir=%d\n", g.gl_pathv[i], s, s == 0 && S_ISDIR(st.st_mode));
    }
    return 0;
}
