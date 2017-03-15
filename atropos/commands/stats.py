# coding: utf-8
"""Collect statistics to use in the QC report.
"""
import re
from atropos.util import CountingDict, NestedDict, qual2int

class BaseDicts(object):
    def __init__(self):
        self.dicts = []
    
    def __getitem__(self, idx):
        return self.dicts[idx]
    
    def extend(self, size):
        n = size - len(self.dicts)
        if n > 0:
            for i in range(n):
                self.dicts.append(self.dict_class())

class BaseCountingDicts(BaseDicts):
    dict_class = CountingDict
    
    def flatten(self, datatype=None):
        """
        Args:
            datatype: 'b' for bases, 'q' for qualities, or None.
        """
        keys = set()
        for d in self.dicts:
            keys.update(d.keys())
        if datatype == "n":
            acgt = ('A','C','G','T')
            N = ('N',) if 'N' in keys else ()
            keys = acgt + tuple(keys - set(acgt + N)) + N
        else:
            keys = tuple(sorted(keys))
        header = tuple(qual2int(k) for k in keys) if datatype == "q" else keys
        return (header, [
            (i,) + tuple(d.get(k, 0) for k in keys)
            for i, d in enumerate(self.dicts, 1)
        ])

class BaseNestedDicts(BaseDicts):
    dict_class = NestedDict
    
    def flatten(self, datatype=None):
        keys1 = set()
        keys2 = set()
        for d1 in self.dicts:
            keys1.update(d1.keys())
            for d2 in d1.values():
                keys2.update(d2.keys())
        keys1 = tuple(sorted(keys1))
        keys2 = tuple(sorted(keys2))
        header = tuple(qual2int(k) for k in keys2) if datatype == "q" else keys2
        return (header, [
            (i, k1,) + tuple(d[k1].get(k2, 0) for k2 in keys2)
            for k1 in keys1
            for i, d in enumerate(self.dicts, 1)
        ])

class ReadStatistics(object):
    """Manages :class:`ReadStatCollector`s for pre- and post-trimming stats.
    
    Args:
        tile_key_regexp: Regular expression to parse read names and capture the
            read's 'tile' ID.
    """
    def __init__(self, mode, paired, **kwargs):
        self.mode = mode
        self.paired = paired
        self.pre = None
        self.post = None
        self.collector_args = kwargs
        
        if mode in ('pre', 'both'):
            self.pre = self._make_collectors()
        if mode in ('post', 'both'):
            self.post = {}
    
    def _make_collectors(self):
        return [
            ReadStatCollector(**self.collector_args)
            for i in range(2 if self.paired else 1)]
    
    def pre_trim(self, record):
        if self.pre is None:
            return
        if self.paired:
            self.pre[0].collect(record[0])
            self.pre[1].collect(record[1])
        else:
            self.pre[0].collect(record)
    
    def post_trim(self, dest, record):
        if self.post is None:
            return
        if dest not in self.post:
            self.post[dest] = self._make_collectors()
        post = self.post[dest]
        post[0].collect(record[0])
        if self.paired:
            post[1].collect(record[1])
    
    def finish(self):
        result = {}
        if self.pre is not None:
            result['pre'] = dict(
                ('read{}'.format(read), stats.finish())
                for read, stats in enumerate(self.pre, 1))
        if self.post is not None:
            result['post'] = {}
            for dest, collectors in self.post.items():
                result[post][dest] = dict(
                    ('read{}'.format(read), stats.finish())
                    for read, stats in enumerate(collectors, 1))
        return result

class ReadStatCollector(object):
    def __init__(self, qualities=None, tile_key_regexp=None):
        # max read length
        self.max_read_len = 0
        # read count
        self.count = 0
        # read length distribution
        self.sequence_lengths = CountingDict()
        # per-sequence GC percentage
        self.sequence_gc = CountingDict()
        # per-position base composition
        self.bases = BaseCountingDicts()
        
        # whether to collect base quality stats
        self.tile_key_regexp = tile_key_regexp
        self.qualities = qualities
        self.sequence_qualities = self.base_qualities = self.tile_base_qualities = None
        if qualities:
            self._init_qualities()
        
        # cache of computed values
        self._cache = {}
    
    def _init_qualities(self):
        # per-sequence mean qualities
        self.sequence_qualities = CountingDict()
        # per-position quality composition
        self.base_qualities = BaseCountingDicts()
        if self.tile_key_regexp:
            self.tile_base_qualities = BaseNestedDicts()
            self.tile_sequence_qualities = NestedDict()
    
    # These are attributes that are computed on the fly. If called by name
    # (without leading '_'), __getattr__ uses the method to compute the value
    # if it is not already cached; on subsequent calls, the cached value is
    # returned.
    
    def _gc_pct(self):
        return sum(base['C'] + base['G'] for base in self.bases) / self.total_bases
    
    def _total_bases(self):
        return sum(length * count for length, count in self.bases.items())
    
    def __getattr__(self, name):
        if name not in self._cache:
            func_name = '_' + name
            if not hasattr(self, func_name):
                raise ValueError("No function named {}".format(func_name))
            func = getattr(self, func_name)
            self._cache[name] = func()
        return self._cache[name]
    
    @property
    def track_tiles(self):
        return self.qualities and self.tile_key_regexp is not None
    
    def collect(self, record):
        if self.qualities is None and record.qualities:
            self.qualities = True
            self._init_qualities()
        
        seq = record.sequence
        seqlen = len(seq)
        gc = round((seq.count('C') + seq.count('G')) * 100 / seqlen)
        
        self.count += 1
        self.sequence_lengths[seqlen] += 1
        self.sequence_gc[gc] += 1
        
        if seqlen > self.max_read_len:
            self._extend_bases(seqlen)
        
        qual = tile = None
        
        if self.qualities:
            quals = record.qualities
            # mean read quality
            meanqual = round(sum(ord(q) for q in quals) / seqlen)
            self.sequence_qualities[meanqual] += 1
            # tile ID
            if self.track_tiles:
                tile_match = self.tile_key_regexp.match(record.name)
                if tile_match:
                    tile = tile_match.group(1)
                    self.tile_sequence_qualities[tile][meanqual] += 1
                else:
                    raise ValueError("{} did not match {}".format(
                        self.tile_key_regexp, record.name))
        
        # per-base nucleotide and quality composition
        for i, (base, qual) in enumerate(zip(seq, quals)):
            self.add_base(i, base, qual, tile)
        
        # TODO: positional k-mer profiles
    
    def add_base(self, i, base, qual=None, tile=None):
        self.bases[i][base] += 1
        if qual:
            self.base_qualities[i][qual] += 1
            if tile:
                self.tile_base_qualities[i][tile][qual] += 1
    
    def _extend_bases(self, new_size):
        self.bases.extend(new_size)
        if self.qualities:
            self.base_qualities.extend(new_size)
            if self.track_tiles:
                self.tile_base_qualities.extend(new_size)
    
    def finish(self):
        result = dict(
            count=self.count,
            length=self.sequence_lengths.sorted_items(),
            gc=self.sequence_gc.sorted_items(),
            bases=self.bases.flatten(datatype="n"))
        if self.sequence_qualities:
            result['qualities'] = self.sequence_qualities.sorted_items()
        if self.base_qualities:
            result['base_qualities'] = self.base_qualities.flatten(datatype="q")
        if self.track_tiles:
            result['tile_base_qualities'] = self.tile_base_qualities.flatten(datatype="q")
            result['tile_sequence_qualities'] = self.tile_sequence_qualities.flatten(shape="wide")
        return result
