/*
 * Hawkeye cache replacement policy for gem5 (ECE 552 / CS 550 project).
 *
 * A. Jain and C. Lin, "Back to the Future: Leveraging Belady's Algorithm for
 * Improved Cache Replacement," ISCA 2016.
 *
 * Hawkeye has three parts:
 *  - OPTgen reconstructs what Belady's OPT would have done on past accesses
 *    to a few sampled sets, using one occupancy vector per sampled set.
 *  - A sampler remembers, for recent lines of the sampled sets, when they
 *    were last accessed and by which PC.
 *  - A PC-indexed table of saturating counters learns from OPTgen whether
 *    the lines a PC brings in are cache-friendly or cache-averse.
 * Lines carry a 3-bit RRPV. Cache-averse lines get the maximum RRPV and are
 * evicted first; cache-friendly lines get 0 and age on every friendly miss.
 *
 * The default parameters follow the authors' CRC2 submission (2K entries of
 * 5-bit counters, a 2800-entry sampler, OPTgen capacity of ways - 2). The
 * paper's configuration (8K entries of 3-bit counters) is reachable through
 * the parameters. Only demand accesses are modeled: the CRC2 code keeps a
 * second predictor for prefetches, and our system has no prefetcher.
 *
 * gem5's replacement-policy interface hands reset() a single line, but a
 * friendly insertion must age the other lines of its set. The cache always
 * calls getVictim() on the set just before it inserts a line, so getVictim()
 * remembers the candidates and reset() ages them, after checking that they
 * belong to the set of the inserted address.
 */

#ifndef __MEM_CACHE_REPLACEMENT_POLICIES_HAWKEYE_RP_HH__
#define __MEM_CACHE_REPLACEMENT_POLICIES_HAWKEYE_RP_HH__

#include <cstdint>
#include <map>
#include <memory>
#include <vector>

#include "base/statistics.hh"
#include "mem/cache/replacement_policies/base.hh"
#include "mem/packet.hh"

namespace gem5
{

struct HawkeyeRPParams;

namespace replacement_policy
{

class Hawkeye : public Base
{
  protected:
    /** Per-line state. */
    struct HawkeyeReplData : ReplacementData
    {
        unsigned rrpv;
        /** PC that last inserted or hit this line, for detraining. */
        uint64_t pc;
        bool valid;

        HawkeyeReplData(unsigned max_rrpv)
          : rrpv(max_rrpv), pc(0), valid(false)
        {}
    };

    /** One OPTgen occupancy vector, for one sampled set. */
    struct OptGen
    {
        std::vector<unsigned> occupancy;
        uint64_t accesses = 0;
        uint64_t optHits = 0;
    };

    /** One sampler entry: a recent line of a sampled set. */
    struct SamplerEntry
    {
        uint64_t lastTime = 0;
        uint64_t pc = 0;
        unsigned lru = 0;
    };

    const unsigned maxRRPV;
    const unsigned numSets;
    const unsigned blockShift;
    const unsigned sampledStride;
    const unsigned optgenVectorSize;
    const unsigned optgenCapacity;
    const unsigned timerSize;
    const unsigned samplerSets;
    const unsigned samplerWays;
    const unsigned predictorEntries;
    const unsigned counterMax;

    /** Predictor counters; >= threshold predicts cache-friendly. */
    mutable std::vector<unsigned> counters;
    const unsigned friendlyThreshold;

    /** Indexed by cache set; only the sampled sets are used. */
    std::vector<OptGen> optgen;
    std::vector<uint64_t> timer;

    /** Sampler: one map from partial tag to entry per sampler set. */
    std::vector<std::map<uint64_t, SamplerEntry>> sampler;

    /** Set seen by the last getVictim(), aged by the next reset(). */
    mutable ReplacementCandidates lastCandidates;

    struct HawkeyeStats : public statistics::Group
    {
        HawkeyeStats(statistics::Group *parent);

        statistics::Scalar demandAccesses;
        statistics::Scalar noPCAccesses;
        statistics::Scalar writebacks;
        statistics::Scalar sampledAccesses;
        statistics::Scalar optgenReuses;
        statistics::Scalar optgenHits;
        statistics::Scalar friendlyPredictions;
        statistics::Scalar aversePredictions;
        statistics::Scalar invalidVictims;
        statistics::Scalar averseVictims;
        statistics::Scalar friendlyVictims;
        statistics::Scalar detrains;
        statistics::Scalar agingSkipped;
        statistics::Formula optgenHitRate;
    };
    mutable HawkeyeStats stats;

    static uint64_t crcHash(uint64_t value);
    unsigned setIndex(Addr addr) const;
    bool isSampled(unsigned set) const;
    bool predict(uint64_t pc) const;
    void train(uint64_t pc, bool friendly) const;

    /** Runs OPTgen and the sampler on an access to a sampled set. */
    void sampleAccess(unsigned set, Addr addr, uint64_t pc);

    /** Shared by reset() (hit = false) and touch() (hit = true). */
    void update(const std::shared_ptr<ReplacementData>& replacement_data,
                const PacketPtr pkt, bool hit);

  public:
    typedef HawkeyeRPParams Params;
    Hawkeye(const Params &p);
    ~Hawkeye() = default;

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

#endif // __MEM_CACHE_REPLACEMENT_POLICIES_HAWKEYE_RP_HH__
