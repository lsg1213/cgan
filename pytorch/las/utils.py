class characterMap:
    def __init__(self):
        self.encodemap = {}
        self.decodemap = {}
        self.mapping()
    
    def __iter__(self):
        return self
    
    def __next__(self):
        return self

    def mapping(self):
        self._mapping('<unk>')
        for i,j in enumerate(range(ord('a'), ord('z') + 1)):
            self.encodemap[f'{chr(j)}'] = i+1
            self.decodemap[i+1] = f'{chr(j)}'
        for i,j in enumerate(range(len(self.encodemap), len(self.encodemap) + 10)):
            self.encodemap[f'{i}'] = j
            self.decodemap[j] = f'{i}'
        self._mapping(' ')
        self._mapping(',')
        self._mapping('.')
        self._mapping("'")
        self._mapping('<sos>')
        self._mapping('<eos>')

    def _mapping(self, data):
        self.encodemap[data] = len(self.encodemap)
        self.decodemap[len(self.decodemap)] = data

    def encode(self, data):
        if data in self.encodemap.keys():
            return self.encodemap[data]
        else:
            return self.encodemap['<unk>']

    def decode(self, data):
        return self.decodemap[data]