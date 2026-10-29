/*
 * Hawkeye cache replacement policy for gem5 (ECE 552 / CS 550 project).
 * See hawkeye_rp.hh for an overview.
 */

#include "mem/cache/replacement_policies/hawkeye_rp.hh"

#include <cassert>

#include "base/intmath.hh"
#include "base/logging.hh"
#include "debug/Hawkeye.hh"
#include "params/HawkeyeRP.hh"

namespace gem5
{

namespace replacement_policy
{

Hawkeye::HawkeyeStats::HawkeyeStats(statistics::Group *parent)
  : statistics::Group(parent),
    ADD_STAT(demandAccesses, statistics::units::Count::get(),
             "Insertions and hits that are not writebacks"),
    ADD_STAT(noPCAccesses, statistics::units::Count::get(),
             "Demand accesses whose request carries no PC"),
    ADD_STAT(writebacks, statistics::units::Count::get(),
             "Writeback insertions and hits (not trained)"),
    ADD_STAT(sampledAccesses, statistics::units::Count::get(),
             "Demand accesses to sampled sets, seen by OPTgen"),
    ADD_STAT(optgenReuses, statistics::units::Count::get(),
             "Sampled accesses that end a usage interval"),
    ADD_STAT(optgenHits, statistics::units::Count::get(),
             "Usage intervals that OPT would have kept in the cache"),
    ADD_STAT(friendlyPredictions, statistics::units::Count::get(),
             "Accesses predicted cache-friendly"),
    ADD_STAT(aversePredictions, statistics::units::Count::get(),
             "Accesses predicted cache-averse"),
    ADD_STAT(invalidVictims, statistics::units::Count::get(),
             "Victims that were invalid lines"),
    ADD_STAT(averseVictims, statistics::units::Count::get(),
             "Victims with the maximum RRPV (cache-averse)"),
    ADD_STAT(friendlyVictims, statistics::units::Count::get(),
             "Victims that were the oldest cache-friendly line"),
    ADD_STAT(detrains, statistics::units::Count::get(),
             "Predictor decrements on friendly evictions in sampled sets"),
    ADD_STAT(agingSkipped, statistics::units::Count::get(),
             "Friendly insertions whose set was not the last victim set"),
    ADD_STAT(optgenHitRate, statistics::units::Ratio::get(),
             "OPT hit rate on the sampled sets",
             optgenHits / sampledAccesses)
{
}

Hawkeye::Hawkeye(const Params &p)
  : Base(p),
    maxRRPV((1u << p.num_rrpv_bits) - 1),
    numSets(p.num_sets),
    blockShift(floorLog2(p.block_size)),
    sampledStride(p.num_sets / p.num_sampled_sets),
    optgenVectorSize(p.optgen_vector_size),
    optgenCapacity(p.optgen_capacity),
    timerSize(p.timer_size),
    samplerSets(p.sampler_entries / p.sampler_ways),
    samplerWays(p.sampler_ways),
    predictorEntries(p.predictor_entries),
    counterMax((1u << p.counter_bits) - 1),
    counters(p.predictor_entries, (counterMax + 1) / 2),
    friendlyThreshold((counterMax + 1) / 2),
    optgen(p.num_sets),
    timer(p.num_sets, 0),
    sampler(p.sampler_entries / p.sampler_ways),
    stats(this)
{
    fatal_if(!isPowerOf2(numSets), "Hawkeye needs a power-of-2 set count.");
    fatal_if(!isPowerOf2(p.block_size), "Block size must be a power of 2.");
    fatal_if(p.num_sampled_sets == 0 || p.num_sampled_sets > numSets ||
             numSets % p.num_sampled_sets != 0,
             "num_sampled_sets must divide num_sets.");
    fatal_if(p.num_rrpv_bits < 2, "Hawkeye needs at least 2 RRPV bits.");
    fatal_if(optgenCapacity == 0, "OPTgen capacity must be positive.");
    fatal_if(optgenVectorSize > timerSize,
             "The timer must cover the occupancy vector.");

    for (unsigned set = 0; set < numSets; set++) {
        if (isSampled(set)) {
            optgen[set].occupancy.assign(optgenVectorSize, 0);
        }
    }
}

uint64_t
Hawkeye::crcHash(uint64_t value)
{
    // Bitwise CRC-32 (reflected polynomial 0xEDB88320), the hash used by
    // the CRC2 code for PCs and sampler tags.
    for (int i = 0; i < 32; i++) {
        value = (value & 1) ? ((value >> 1) ^ 0xEDB88320ULL) : (value >> 1);
    }
    return value;
}

unsigned
Hawkeye::setIndex(Addr addr) const
{
    return (addr >> blockShift) & (numSets - 1);
}

bool
Hawkeye::isSampled(unsigned set) const
{
    // One set in every sampledStride sets, with the offset inside each
    // group of sampledStride sets moving diagonally, so that the sampled
    // sets do not share their low index bits.
    return (set % sampledStride) == ((set / sampledStride) % sampledStride);
}

bool
Hawkeye::predict(uint64_t pc) const
{
    return counters[crcHash(pc) % predictorEntries] >= friendlyThreshold;
}

void
Hawkeye::train(uint64_t pc, bool friendly) const
{
    unsigned &counter = counters[crcHash(pc) % predictorEntries];
    if (friendly && counter < counterMax) {
        counter++;
    } else if (!friendly && counter > 0) {
        counter--;
    }
}

void
Hawkeye::sampleAccess(unsigned set, Addr addr, uint64_t pc)
{
    stats.sampledAccesses++;
    OptGen &og = optgen[set];
    const uint64_t now = timer[set];
    const unsigned curr = now % optgenVectorSize;

    auto &sampler_set = sampler[(addr >> blockShift) % samplerSets];
    const uint64_t tag = crcHash(addr >> 12) % 256;
    auto it = sampler_set.find(tag);

    if (it != sampler_set.end()) {
        // The line was seen before: its usage interval ends here. OPT keeps
        // it if no point of the interval is already at full occupancy.
        SamplerEntry &entry = it->second;
        uint64_t elapsed = (now + timerSize - entry.lastTime) % timerSize;
        bool opt_hit = false;
        if (elapsed <= optgenVectorSize) {
            const unsigned last = entry.lastTime % optgenVectorSize;
            opt_hit = true;
            for (unsigned i = last; i != curr; i = (i + 1) % optgenVectorSize) {
                if (og.occupancy[i] >= optgenCapacity) {
                    opt_hit = false;
                    break;
                }
            }
            if (opt_hit) {
                for (unsigned i = last; i != curr;
                     i = (i + 1) % optgenVectorSize) {
                    og.occupancy[i]++;
                }
            }
        }
        stats.optgenReuses++;
        if (opt_hit) {
            stats.optgenHits++;
            og.optHits++;
        }
        DPRINTF(Hawkeye, "OPTgen set %u addr %#x: reuse after %u, OPT %s, "
                "train pc %#x %s\n", set, addr, elapsed,
                opt_hit ? "hit" : "miss", entry.pc,
                opt_hit ? "up" : "down");
        train(entry.pc, opt_hit);

        // Move the entry to the MRU position of its sampler set.
        for (auto &other : sampler_set) {
            if (other.second.lru < entry.lru) {
                other.second.lru++;
            }
        }
    } else {
        // First sighting: make room in the sampler set, then insert.
        if (sampler_set.size() == samplerWays) {
            for (auto e = sampler_set.begin(); e != sampler_set.end(); ++e) {
                if (e->second.lru == samplerWays - 1) {
                    sampler_set.erase(e);
                    break;
                }
            }
        }
        for (auto &other : sampler_set) {
            other.second.lru++;
        }
        it = sampler_set.emplace(tag, SamplerEntry()).first;
    }

    og.accesses++;
    og.occupancy[curr] = 0;
    it->second.lastTime = now;
    it->second.pc = pc;
    it->second.lru = 0;
    timer[set] = (now + 1) % timerSize;
}

void
Hawkeye::update(const std::shared_ptr<ReplacementData>& replacement_data,
                const PacketPtr pkt, bool hit)
{
    auto data = std::static_pointer_cast<HawkeyeReplData>(replacement_data);

    // Writebacks carry no PC and are not trained on, as in the CRC2 code.
    // A line inserted by a writeback starts as cache-averse.
    if (pkt->isWriteback()) {
        stats.writebacks++;
        if (!hit) {
            data->rrpv = maxRRPV;
            data->pc = 0;
            data->valid = true;
            lastCandidates.clear();
        }
        return;
    }

    stats.demandAccesses++;
    uint64_t pc = 0;
    if (pkt->req->hasPC()) {
        pc = pkt->req->getPC();
    } else {
        stats.noPCAccesses++;
    }

    const Addr addr = pkt->getAddr() & ~Addr((1ULL << blockShift) - 1);
    const unsigned set = setIndex(addr);
    if (isSampled(set)) {
        sampleAccess(set, addr, pc);
    }

    const bool friendly = predict(pc);
    data->pc = pc;
    data->valid = true;

    if (!friendly) {
        stats.aversePredictions++;
        data->rrpv = maxRRPV;
    } else {
        stats.friendlyPredictions++;
        data->rrpv = 0;
        // A friendly insertion ages the other friendly lines of the set,
        // unless one of them already sits just below the maximum RRPV.
        if (!hit) {
            if (lastCandidates.empty() ||
                lastCandidates[0]->getSet() != set) {
                stats.agingSkipped++;
            } else {
                bool saturated = false;
                for (const auto &c : lastCandidates) {
                    auto d = std::static_pointer_cast<HawkeyeReplData>(
                        c->replacementData);
                    if (d != data && d->valid && d->rrpv == maxRRPV - 1) {
                        saturated = true;
                    }
                }
                if (!saturated) {
                    for (const auto &c : lastCandidates) {
                        auto d = std::static_pointer_cast<HawkeyeReplData>(
                            c->replacementData);
                        if (d != data && d->valid && d->rrpv < maxRRPV - 1) {
                            d->rrpv++;
                        }
                    }
                }
            }
        }
    }
    if (!hit) {
        lastCandidates.clear();
    }

    DPRINTF(Hawkeye, "%s set %u addr %#x pc %#x: %s, rrpv %u\n",
            hit ? "hit" : "fill", set, addr, pc,
            friendly ? "friendly" : "averse", data->rrpv);
}

void
Hawkeye::invalidate(const std::shared_ptr<ReplacementData>& replacement_data)
{
    std::static_pointer_cast<HawkeyeReplData>(replacement_data)->valid =
        false;
}

void
Hawkeye::touch(const std::shared_ptr<ReplacementData>& replacement_data,
               const PacketPtr pkt)
{
    update(replacement_data, pkt, true);
}

void
Hawkeye::touch(const std::shared_ptr<ReplacementData>& replacement_data)
    const
{
    panic("Hawkeye needs the packet to train its predictor.");
}

void
Hawkeye::reset(const std::shared_ptr<ReplacementData>& replacement_data,
               const PacketPtr pkt)
{
    update(replacement_data, pkt, false);
}

void
Hawkeye::reset(const std::shared_ptr<ReplacementData>& replacement_data)
    const
{
    panic("Hawkeye needs the packet to train its predictor.");
}

ReplaceableEntry*
Hawkeye::getVictim(const ReplacementCandidates& candidates) const
{
    assert(!candidates.empty());
    lastCandidates = candidates;

    for (const auto &c : candidates) {
        if (!std::static_pointer_cast<HawkeyeReplData>(
                c->replacementData)->valid) {
            stats.invalidVictims++;
            return c;
        }
    }

    // Cache-averse lines go first.
    for (const auto &c : candidates) {
        if (std::static_pointer_cast<HawkeyeReplData>(
                c->replacementData)->rrpv == maxRRPV) {
            stats.averseVictims++;
            DPRINTF(Hawkeye, "victim set %u way %u: averse\n",
                    c->getSet(), c->getWay());
            return c;
        }
    }

    // Otherwise evict the oldest friendly line (the last one on a tie, as
    // in the CRC2 code) and detrain its PC if the set is sampled.
    ReplaceableEntry *victim = nullptr;
    unsigned max_rrpv = 0;
    for (const auto &c : candidates) {
        unsigned rrpv = std::static_pointer_cast<HawkeyeReplData>(
            c->replacementData)->rrpv;
        if (rrpv >= max_rrpv) {
            max_rrpv = rrpv;
            victim = c;
        }
    }
    stats.friendlyVictims++;
    if (isSampled(victim->getSet())) {
        uint64_t pc = std::static_pointer_cast<HawkeyeReplData>(
            victim->replacementData)->pc;
        train(pc, false);
        stats.detrains++;
    }
    DPRINTF(Hawkeye, "victim set %u way %u: oldest friendly, rrpv %u\n",
            victim->getSet(), victim->getWay(), max_rrpv);
    return victim;
}

std::shared_ptr<ReplacementData>
Hawkeye::instantiateEntry()
{
    return std::shared_ptr<ReplacementData>(new HawkeyeReplData(maxRRPV));
}

} // namespace replacement_policy
} // namespace gem5
