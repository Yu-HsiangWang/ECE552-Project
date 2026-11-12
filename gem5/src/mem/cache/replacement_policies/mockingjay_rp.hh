/*
 * Mockingjay cache replacement policy for gem5 (ECE 552 / CS 550 project).
 *
 * I. Shah, A. Jain, and C. Lin, "Effective Mimicry of Belady's MIN Policy,"
 * HPCA 2022.
 *
 * Mockingjay has three parts:
 *  - A sampled cache records recent accesses to a few sampled sets, and
 *    measures each line's reuse distance (accesses to its set between two
 *    uses of the line). A line not reused within INF_RD accesses counts as
 *    never reused.
 *  - A reuse distance predictor (RDP) learns, per PC signature (the PC hash
 *    includes the hit bit), the typical reuse distance of the lines that
 *    signature touches.
 *  - Every line carries a signed estimated time remaining (ETR) until its
 *    next use, set from the RDP on every access and decremented once every
 *    GRANULARITY accesses to its set. The victim is the line with the
 *    largest |ETR|: the one reused furthest in the future, or the most
 *    overdue one.
 *
 * Parameters are derived from the LLC geometry exactly as in the public
 * single-core ChampSim implementation (whose storage matches the paper's
 * 31.91 KB for a 2 MB, 16-way LLC) and as in our reference model,
 * tools/mockingjay_ref.py.
 *
 * Differences forced by gem5's replacement-policy interface (see
 * results/05_mockingjay_ref.md):
 *  - A policy cannot refuse an insertion. A line that Mockingjay would
 *    bypass is inserted; its ETR is then the largest of its set (or the
 *    maximum), so it is the next victim. The model's "no bypass" mode.
 *  - The policy sees only the accessed line, so it cannot age the whole set
 *    in place. Each set keeps an aging count (ticks), each line remembers
 *    the count when its ETR was set, and the current ETR is computed when
 *    it is read. The model checks that this makes the same decisions.
 *  - CleanEvict notices from the L2 are not accesses and are ignored.
 *    Writebacks are not trained on; a line filled by a writeback gets
 *    ETR = -INF_ETR (as in the ChampSim code), a writeback hit changes
 *    nothing.
 */

#ifndef __MEM_CACHE_REPLACEMENT_POLICIES_MOCKINGJAY_RP_HH__
#define __MEM_CACHE_REPLACEMENT_POLICIES_MOCKINGJAY_RP_HH__

#include <array>
#include <cstdint>
#include <memory>
#include <unordered_map>
#include <vector>

#include "base/statistics.hh"
#include "mem/cache/replacement_policies/base.hh"
#include "mem/packet.hh"

namespace gem5
{

struct MockingjayRPParams;

namespace replacement_policy
{

class Mockingjay : public Base
{
  protected:
    /** Per-line state. */
    struct MockingjayReplData : ReplacementData
    {
        /** ETR when it was last set, and the set's aging count then. */
        int etr = 0;
        uint64_t etrTick = 0;
        bool valid = false;
        /** Filled by an instruction fetch (for the statistics only). */
        bool inst = false;
        /** Position in the cache, learned in getVictim (for the log). */
        unsigned set = 0;
        unsigned way = 0;
    };

    /** One sampled-cache line. */
    struct SampledLine
    {
        bool valid = false;
        uint64_t tag = 0;
        uint64_t sig = 0;
        unsigned timestamp = 0;
    };

    static constexpr unsigned HISTORY = 8;
    static constexpr unsigned GRANULARITY = 8;
    static constexpr unsigned SC_WAYS = 5;
    static constexpr unsigned LOG2_SC_SETS = 4;
    static constexpr unsigned TS_BITS = 8;

    const unsigned numSets;
    const unsigned numWays;
    const unsigned log2Sets;
    const unsigned log2Block;
    const unsigned log2Size;
    const unsigned log2Sampled;
    const int infRd;
    const int infEtr;
    const int maxRd;
    const unsigned tagBits;
    const unsigned sigBits;

    /** Insert instruction-fetch lines with ETR 0 and keep their fetch
     *  addresses out of the sampled cache (not in the paper). */
    const bool instNoPredict;

    /** RDP: predicted reuse distance per signature, -1 = no prediction. */
    std::vector<int> rdp;

    /** Per set: accesses since the last aging step, and aging count. */
    std::vector<unsigned> clock;
    std::vector<uint64_t> ticks;
    /** Per set (only sampled sets use it): 8-bit access timestamp. */
    std::vector<unsigned> timestamp;

    /** Sampled cache, indexed like the ChampSim code. */
    std::unordered_map<uint64_t, std::array<SampledLine, SC_WAYS>>
        sampledCache;

    /** What the last getVictim() saw, for the bypass statistic. */
    mutable int lastVictimSet = -1;
    mutable int lastMaxEtr = 0;
    mutable bool lastVictimInvalid = false;

    struct MockingjayStats : public statistics::Group
    {
        MockingjayStats(statistics::Group *parent);

        statistics::Scalar demandAccesses;
        statistics::Scalar demandHits;
        statistics::Scalar noPCAccesses;
        statistics::Scalar instAccesses;
        statistics::Scalar writebacks;
        statistics::Scalar writebackFills;
        statistics::Scalar cleanEvicts;
        statistics::Scalar sampledAccesses;
        statistics::Scalar rdpTrains;
        statistics::Scalar rdpDetrains;
        statistics::Scalar noPrediction;
        statistics::Scalar predictedNoReuse;
        statistics::Scalar bypassFills;
        statistics::Scalar instBypassFills;
        statistics::Scalar invalidVictims;
        statistics::Scalar overdueVictims;
        statistics::Scalar futureVictims;
        statistics::Scalar instVictims;
    };
    mutable MockingjayStats stats;

    static uint64_t crc3(uint64_t value);
    uint64_t signature(uint64_t pc, bool hit) const;
    unsigned setIndex(Addr addr) const;
    bool isSampled(unsigned set) const;
    int currentEtr(const MockingjayReplData &d) const;
    void setEtr(MockingjayReplData &d, unsigned set, int value) const;
    int temporalDifference(int init, int sample) const;
    unsigned elapsed(unsigned now, unsigned then) const;
    void detrain(SampledLine &line);
    void train(unsigned set, Addr addr, uint64_t sig);
    void age(unsigned set);

    /** Shared by reset() (hit = false) and touch() (hit = true). */
    void update(const std::shared_ptr<ReplacementData>& replacement_data,
                const PacketPtr pkt, bool hit);

  public:
    typedef MockingjayRPParams Params;
    Mockingjay(const Params &p);
    ~Mockingjay() = default;

    void invalidate(const std::shared_ptr<ReplacementData>& replacement_data)
        override;
    void touch(const std::shared_ptr<ReplacementData>& replacement_data,
               const PacketPtr pkt) override;
    void touch(const std::shared_ptr<ReplacementData>& replacement_data)
        const override;
    void reset(const std::shared_ptr<ReplacementData>& replacement_data,
               const PacketPtr pkt) override;
    void reset(const std::shared_ptr<ReplacementData>& replacement_data)
        const override;
    ReplaceableEntry* getVictim(const ReplacementCandidates& candidates)
        const override;
    std::shared_ptr<ReplacementData> instantiateEntry() override;
};

} // namespace replacement_policy
} // namespace gem5

#endif // __MEM_CACHE_REPLACEMENT_POLICIES_MOCKINGJAY_RP_HH__
