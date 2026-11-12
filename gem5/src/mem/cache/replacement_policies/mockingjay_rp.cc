/*
 * Mockingjay cache replacement policy for gem5 (ECE 552 / CS 550 project).
 * See mockingjay_rp.hh for an overview. Every step mirrors the class
 * Mockingjay in tools/mockingjay_ref.py (with bypass=False, lazy=True), and
 * `mockingjay_ref.py check` replays the debug log of this file through it.
 */

#include "mem/cache/replacement_policies/mockingjay_rp.hh"

#include <algorithm>
#include <cassert>
#include <cstdlib>

#include "base/intmath.hh"
#include "base/logging.hh"
#include "debug/Mockingjay.hh"
#include "params/MockingjayRP.hh"

namespace gem5
{

namespace replacement_policy
{

Mockingjay::MockingjayStats::MockingjayStats(statistics::Group *parent)
  : statistics::Group(parent),
    ADD_STAT(demandAccesses, statistics::units::Count::get(),
             "Fills and hits that are not writebacks"),
    ADD_STAT(demandHits, statistics::units::Count::get(),
             "Demand accesses that hit"),
    ADD_STAT(noPCAccesses, statistics::units::Count::get(),
             "Demand accesses whose request carries no PC"),
    ADD_STAT(instAccesses, statistics::units::Count::get(),
             "Demand accesses by instruction fetches"),
    ADD_STAT(writebacks, statistics::units::Count::get(),
             "Writeback fills and hits (not trained)"),
    ADD_STAT(writebackFills, statistics::units::Count::get(),
             "Lines filled by a writeback (ETR = -INF_ETR)"),
    ADD_STAT(cleanEvicts, statistics::units::Count::get(),
             "CleanEvict notices from the upper cache (ignored)"),
    ADD_STAT(sampledAccesses, statistics::units::Count::get(),
             "Demand accesses to sampled sets, seen by the sampled cache"),
    ADD_STAT(rdpTrains, statistics::units::Count::get(),
             "RDP updates from a measured reuse distance"),
    ADD_STAT(rdpDetrains, statistics::units::Count::get(),
             "RDP updates from a line that left the sampled cache unused"),
    ADD_STAT(noPrediction, statistics::units::Count::get(),
             "Demand accesses whose signature has no RDP entry (ETR 0)"),
    ADD_STAT(predictedNoReuse, statistics::units::Count::get(),
             "Demand accesses predicted beyond MAX_RD (ETR = INF_ETR)"),
    ADD_STAT(bypassFills, statistics::units::Count::get(),
             "Fills that Mockingjay would bypass (inserted as next victim)"),
    ADD_STAT(instBypassFills, statistics::units::Count::get(),
             "Bypass fills by instruction fetches"),
    ADD_STAT(invalidVictims, statistics::units::Count::get(),
             "Victims that were invalid lines"),
    ADD_STAT(overdueVictims, statistics::units::Count::get(),
             "Victims with a negative ETR (overdue)"),
    ADD_STAT(futureVictims, statistics::units::Count::get(),
             "Victims with a non-negative ETR (reused furthest away)"),
    ADD_STAT(instVictims, statistics::units::Count::get(),
             "Valid victims filled by an instruction fetch")
{
}

Mockingjay::Mockingjay(const Params &p)
  : Base(p),
    numSets(p.num_sets),
    numWays(p.num_ways),
    log2Sets(floorLog2(p.num_sets)),
    log2Block(floorLog2(p.block_size)),
    log2Size(floorLog2(p.num_sets) + floorLog2(p.num_ways) +
             floorLog2(p.block_size)),
    log2Sampled(log2Size - 16),
    infRd(p.num_ways * HISTORY - 1),
    infEtr(p.num_ways * HISTORY / GRANULARITY - 1),
    maxRd(p.num_ways * HISTORY - 1 - 22),
    tagBits(31 - log2Size),
    sigBits(log2Size - 10),
    instNoPredict(p.inst_no_predict),
    rdp(1ULL << (log2Size - 10), -1),
    clock(p.num_sets, GRANULARITY),
    ticks(p.num_sets, 0),
    timestamp(p.num_sets, 0),
    stats(this)
{
    fatal_if(!isPowerOf2(numSets), "Mockingjay needs a power-of-2 set count.");
    fatal_if(!isPowerOf2(numWays), "Mockingjay needs power-of-2 ways.");
    fatal_if(!isPowerOf2(p.block_size), "Block size must be a power of 2.");
    fatal_if(log2Size < 17 || log2Size > 26,
             "Mockingjay's parameters are derived for 128 KB to 64 MB LLCs.");
    fatal_if(log2Sets <= log2Sampled, "Too few sets for the sampled sets.");
}

uint64_t
Mockingjay::crc3(uint64_t value)
{
    // Three steps of the reflected CRC-32 (0xEDB88320), as in the ChampSim
    // code's PC hash.
    for (int i = 0; i < 3; i++) {
        value = (value & 1) ? ((value >> 1) ^ 0xEDB88320ULL) : (value >> 1);
    }
    return value;
}

uint64_t
Mockingjay::signature(uint64_t pc, bool hit) const
{
    // The prefetch bit is always 0: our system has no hardware prefetcher.
    const uint64_t v = ((pc << 1) | (hit ? 1 : 0)) << 1;
    return crc3(v) & ((1ULL << sigBits) - 1);
}

unsigned
Mockingjay::setIndex(Addr addr) const
{
    return (addr >> log2Block) & (numSets - 1);
}

bool
Mockingjay::isSampled(unsigned set) const
{
    const unsigned n = log2Sets - log2Sampled;
    const unsigned mask = (1u << n) - 1;
    return (set & mask) == ((set >> (log2Sets - n)) & mask);
}

int
Mockingjay::currentEtr(const MockingjayReplData &d) const
{
    // Lines at +-INF_ETR do not age; the others lose one step per aging
    // step of their set since their ETR was set, down to -INF_ETR.
    if (std::abs(d.etr) >= infEtr) {
        return d.etr;
    }
    const int64_t aged = int64_t(d.etr) - int64_t(ticks[d.set] - d.etrTick);
    return int(std::max<int64_t>(aged, -infEtr));
}

void
Mockingjay::setEtr(MockingjayReplData &d, unsigned set, int value) const
{
    d.etr = value;
    d.etrTick = ticks[set];
}

int
Mockingjay::temporalDifference(int init, int sample) const
{
    if (sample > init) {
        return std::min(init + std::min(1, (sample - init) / 16), infRd);
    }
    if (sample < init) {
        return std::max(init - std::min(1, (init - sample) / 16), 0);
    }
    return init;
}

unsigned
Mockingjay::elapsed(unsigned now, unsigned then) const
{
    return now >= then ? now - then : now + (1u << TS_BITS) - then;
}

void
Mockingjay::detrain(SampledLine &line)
{
    if (!line.valid) {
        return;
    }
    int &rd = rdp[line.sig];
    rd = rd < 0 ? infRd : std::min(rd + 1, infRd);
    line.valid = false;
    stats.rdpDetrains++;
}

void
Mockingjay::train(unsigned set, Addr addr, uint64_t sig)
{
    stats.sampledAccesses++;
    const uint64_t idx =
        (addr >> log2Block) & ((1ULL << (LOG2_SC_SETS + log2Sets)) - 1);
    const uint64_t tag = (addr >> (log2Sets + log2Block + LOG2_SC_SETS)) &
        ((1ULL << tagBits) - 1);
    auto &lines = sampledCache[idx];
    const unsigned now = timestamp[set];

    // A reuse of a line in the sampled cache trains the signature that
    // touched it last with the measured reuse distance.
    for (auto &line : lines) {
        if (line.valid && line.tag == tag) {
            const int sample = elapsed(now, line.timestamp);
            if (sample <= infRd) {
                int &rd = rdp[line.sig];
                rd = rd < 0 ? sample : temporalDifference(rd, sample);
                line.valid = false;
                stats.rdpTrains++;
                DPRINTF(Mockingjay, "MJ train sig %#x sample %d rd %d\n",
                        line.sig, sample, rd);
            }
            break;
        }
    }

    // Make room: lines older than INF_RD were not reused in time and
    // detrain their signature; otherwise the oldest line goes.
    int lru_way = -1;
    int lru_rd = -1;
    for (unsigned w = 0; w < SC_WAYS; w++) {
        if (!lines[w].valid) {
            lru_way = w;
            lru_rd = infRd + 1;
            continue;
        }
        const int sample = elapsed(now, lines[w].timestamp);
        if (sample > infRd) {
            lru_way = w;
            lru_rd = infRd + 1;
            detrain(lines[w]);
        } else if (sample > lru_rd) {
            lru_way = w;
            lru_rd = sample;
        }
    }
    assert(lru_way >= 0);
    detrain(lines[lru_way]);
    for (auto &line : lines) {
        if (!line.valid) {
            line.valid = true;
            line.tag = tag;
            line.sig = sig;
            line.timestamp = now;
            break;
        }
    }
    timestamp[set] = (now + 1) % (1u << TS_BITS);
}

void
Mockingjay::age(unsigned set)
{
    if (clock[set] == GRANULARITY) {
        ticks[set]++;
        clock[set] = 0;
    }
    clock[set]++;
}

void
Mockingjay::update(const std::shared_ptr<ReplacementData>& replacement_data,
                   const PacketPtr pkt, bool hit)
{
    auto data = std::static_pointer_cast<MockingjayReplData>(
        replacement_data);

    // gem5 looks up the tags for every packet, so a CleanEvict from the L2
    // (the L2 dropped a clean copy) also lands here. It is not a program
    // access.
    if (pkt->cmd == MemCmd::CleanEvict) {
        stats.cleanEvicts++;
        return;
    }

    const Addr addr = pkt->getAddr() & ~Addr((1ULL << log2Block) - 1);
    const unsigned set = setIndex(addr);

    if (pkt->isWriteback()) {
        stats.writebacks++;
        if (!hit) {
            stats.writebackFills++;
            data->valid = true;
            data->inst = false;
            setEtr(*data, set, -infEtr);
        }
        DPRINTF(Mockingjay, "MJ %s set %u way %u addr %#x pc 0 etr %d\n",
                hit ? "wbhit" : "wbfill", set, data->way, addr,
                hit ? currentEtr(*data) : data->etr);
        lastVictimSet = -1;
        return;
    }

    stats.demandAccesses++;
    if (hit) {
        stats.demandHits++;
    }
    uint64_t pc = 0;
    if (pkt->req->hasPC()) {
        pc = pkt->req->getPC();
    } else {
        stats.noPCAccesses++;
    }
    const bool inst = pkt->req->isInstFetch();
    if (inst) {
        stats.instAccesses++;
    }
    const bool predict = !(instNoPredict && inst);

    // The bypass decision of the original design, which gem5 cannot take:
    // compare the miss signature's prediction with the set's largest |ETR|
    // that getVictim() saw.
    if (!hit && predict && lastVictimSet == int(set) && !lastVictimInvalid) {
        const int rd = rdp[signature(pc, false)];
        if (rd >= 0 && (rd > maxRd || rd / int(GRANULARITY) > lastMaxEtr)) {
            stats.bypassFills++;
            if (inst) {
                stats.instBypassFills++;
            }
        }
    }
    if (!hit) {
        lastVictimSet = -1;
        data->inst = inst;
    }
    data->valid = true;

    const uint64_t sig = signature(pc, hit);
    if (predict && isSampled(set)) {
        train(set, addr, sig);
    }
    age(set);

    int etr = 0;
    const int rd = predict ? rdp[sig] : -1;
    if (rd < 0) {
        stats.noPrediction++;
    } else if (rd > maxRd) {
        stats.predictedNoReuse++;
        etr = infEtr;
    } else {
        etr = rd / int(GRANULARITY);
    }
    setEtr(*data, set, etr);

    DPRINTF(Mockingjay, "MJ %s set %u way %u addr %#x pc %#x etr %d\n",
            hit ? "hit" : "fill", set, data->way, addr, pc, etr);
}

void
Mockingjay::invalidate(
    const std::shared_ptr<ReplacementData>& replacement_data)
{
    auto data = std::static_pointer_cast<MockingjayReplData>(
        replacement_data);
    if (data->valid) {
        DPRINTF(Mockingjay, "MJ inval set %u way %u\n", data->set, data->way);
    }
    data->valid = false;
}

void
Mockingjay::touch(const std::shared_ptr<ReplacementData>& replacement_data,
                  const PacketPtr pkt)
{
    update(replacement_data, pkt, true);
}

void
Mockingjay::touch(const std::shared_ptr<ReplacementData>& replacement_data)
    const
{
    panic("Mockingjay needs the packet to train its predictor.");
}

void
Mockingjay::reset(const std::shared_ptr<ReplacementData>& replacement_data,
                  const PacketPtr pkt)
{
    update(replacement_data, pkt, false);
}

void
Mockingjay::reset(const std::shared_ptr<ReplacementData>& replacement_data)
    const
{
    panic("Mockingjay needs the packet to train its predictor.");
}

ReplaceableEntry*
Mockingjay::getVictim(const ReplacementCandidates& candidates) const
{
    assert(!candidates.empty());
    for (const auto &c : candidates) {
        auto d = std::static_pointer_cast<MockingjayReplData>(
            c->replacementData);
        d->set = c->getSet();
        d->way = c->getWay();
    }
    lastVictimSet = candidates[0]->getSet();
    lastVictimInvalid = false;

    for (const auto &c : candidates) {
        if (!std::static_pointer_cast<MockingjayReplData>(
                c->replacementData)->valid) {
            stats.invalidVictims++;
            lastVictimInvalid = true;
            DPRINTF(Mockingjay, "MJ victim set %u way %u invalid\n",
                    c->getSet(), c->getWay());
            return c;
        }
    }

    // The largest |ETR| goes; on a tie a negative (overdue) ETR wins over
    // a positive one, as in the ChampSim code.
    ReplaceableEntry *victim = candidates[0];
    int max_etr = 0;
    int victim_etr = 0;
    for (const auto &c : candidates) {
        const int e = currentEtr(*std::static_pointer_cast<
            MockingjayReplData>(c->replacementData));
        if (std::abs(e) > max_etr || (std::abs(e) == max_etr && e < 0)) {
            max_etr = std::abs(e);
            victim_etr = e;
            victim = c;
        }
    }
    lastMaxEtr = max_etr;
    if (victim_etr < 0) {
        stats.overdueVictims++;
    } else {
        stats.futureVictims++;
    }
    if (std::static_pointer_cast<MockingjayReplData>(
            victim->replacementData)->inst) {
        stats.instVictims++;
    }
    DPRINTF(Mockingjay, "MJ victim set %u way %u etr %d\n",
            victim->getSet(), victim->getWay(), victim_etr);
    return victim;
}

std::shared_ptr<ReplacementData>
Mockingjay::instantiateEntry()
{
    return std::shared_ptr<ReplacementData>(new MockingjayReplData());
}

} // namespace replacement_policy
} // namespace gem5
