"""
Helps starting the wmediumd service

author: Patrick Grosse (patrick.grosse@uni-muenster.de)
"""

import os
import tempfile
from mininet.log import info, debug
from wifiModule import module


class WmediumdConn(object):
    is_initialized = False
    intfrefs = None
    links = None
    executable = None
    auto_add_links = None
    default_auto_snr = None

    is_connected = False
    wmd_process = None
    wmd_config_name = None

    @classmethod
    def set_wmediumd_data(cls, intfrefs, links, executable='wmediumd', auto_add_links=True,
                          default_auto_snr=0):
        """
        Set the data for the wmediumd daemon

        :param intfrefs: A list of all WmediumdIntfRef that should be managed in wmediumd
        :param links: A list of WmediumdLink
        :param executable: The wmediumd executable
        :param auto_add_links: If true, it will add all missing links pairs with the default_auto_snr as SNR
        :param default_auto_snr: The default SNR

        :type intfrefs: list of StaticWmediumdIntfRef
        :type links: list of WmediumdLink
        """
        cls.intfrefs = intfrefs
        cls.links = links
        cls.executable = executable
        cls.auto_add_links = auto_add_links
        cls.default_auto_snr = default_auto_snr
        cls.is_initialized = True

    @classmethod
    def intercept_module_loading(cls):
        """
        This method can be called before initializing the Mininet net
        to prevent the stations from reaching each other from the beginning.

        Alternative: Call connect_wmediumd() when the net is built
        """
        if not cls.is_initialized:
            raise Exception("Use set_wmediumd_data first to set the required data")

        @classmethod
        def intercepted_loading(other_cls, wifiRadios, alternativeModule=''):
            if alternativeModule != '':
                raise Exception("alternativeModule is not supported by wmediumd")
            os.system('modprobe mac80211_hwsim radios=%s' % wifiRadios)
            debug('Loading %s virtual interfaces\n' % wifiRadios)
            cls.connect_wmediumd()

        module.loadModule = intercepted_loading

    @classmethod
    def connect_wmediumd(cls):
        """
        This method can be called after initializing the Mininet net
        to prevent the stations from reaching each other.

        The stations can reach each other before this method is called and
        some scripts may use some kind of a cache (eg. iw station dump)

        Alternative: Call intercept_module_loading() before the net is built
        """
        if not cls.is_initialized:
            raise Exception("Use set_wmediumd_data first to set the required data")

        if cls.is_connected:
            raise Exception('wmediumd is already initialized')

        mappedintfrefs = {}
        mappedlinks = {}

        # Map all links using the interface identifier and check for missing interfaces in the  intfrefs list
        for link in cls.links:
            link_id = link.sta1intfref.identifier() + '/' + link.sta2intfref.identifier()
            mappedlinks[link_id] = link
            found1 = False
            found2 = False
            for intfref in cls.intfrefs:
                if link.sta1intfref.get_station_name() == intfref.get_station_name():
                    if link.sta1intfref.get_station_name() == intfref.get_station_name():
                        found1 = True
                if link.sta2intfref.get_station_name() == intfref.get_station_name():
                    if link.sta2intfref.get_station_name() == intfref.get_station_name():
                        found2 = True
            if not found1:
                raise Exception('%s is not part of the managed interfaces' % link.sta1intfref.identifier())
                pass
            if not found2:
                raise Exception('%s is not part of the managed interfaces' % link.sta2intfref.identifier())

        # Auto add links
        if cls.auto_add_links:
            for intfref1 in cls.intfrefs:
                for intfref2 in cls.intfrefs:
                    if intfref1 != intfref2:
                        link_id = intfref1.identifier() + '/' + intfref2.identifier()
                        mappedlinks.setdefault(link_id, WmediumdLink(intfref1, intfref2, cls.default_auto_snr))

        # Create wmediumd config
        wmd_config = tempfile.NamedTemporaryFile(prefix='mn_wmd_config_', suffix='.cfg', delete=False)
        cls.wmd_config_name = wmd_config.name
        info("Name of wmediumd config: %s\n" % cls.wmd_config_name)
        configstr = 'ifaces :\n{\n\tids = ['
        intfref_id = 0
        for intfref in cls.intfrefs:
            if intfref_id != 0:
                configstr += ', '
            grepped_mac = intfref.get_intf_mac()
            configstr += '"%s"' % grepped_mac
            mappedintfrefs[intfref.identifier()] = intfref_id
            intfref_id += 1
        configstr += '];\n\tlinks = ('
        first_link = True
        for mappedlink in mappedlinks.itervalues():
            id1 = mappedlink.sta1intfref.identifier()
            id2 = mappedlink.sta2intfref.identifier()
            if first_link:
                first_link = False
            else:
                configstr += ','
            configstr += '\n\t\t(%d, %d, %d)' % (
                mappedintfrefs[id1], mappedintfrefs[id2],
                mappedlink.snr)
        configstr += '\n\t);\n}'
        wmd_config.write(configstr)
        wmd_config.close()

        # Start wmediumd using the created config
        os.system('tmux new -s mnwmd -d')
        os.system('tmux send-keys -t mnwmd \'%s -c %s\' C-m' % (cls.executable, cls.wmd_config_name))
        cls.is_connected = True

    @classmethod
    def disconnect_wmediumd(cls):
        """
        Kill the wmediumd process if running and delete the config
        """
        if cls.is_connected:
            try:
                os.remove(cls.wmd_config_name)
            except OSError:
                pass
            os.system('tmux kill-session -t mnwmd')
            cls.is_connected = False
        else:
            raise Exception('wmediumd is not initialized')


class WmediumdLink(object):
    def __init__(self, sta1intfref, sta2intfref, snr=10):
        """
        Describes a link between two interfaces using the SNR

        :param sta1intfref: Instance of StaticWmediumdIntfRef
        :param sta2intfref: Instance of StaticWmediumdIntfRef
        :param snr: Signal Noise Ratio as int

        :type sta1intfref: StaticWmediumdIntfRef
        :type sta2intfref: StaticWmediumdIntfRef
        """
        self.sta1intfref = sta1intfref
        self.sta2intfref = sta2intfref
        self.snr = snr


class StaticWmediumdIntfRef(object):
    def __init__(self, staname, intfname, intfmac):
        """
        An unambiguous reference to an interface of a station

        :param staname: Station name
        :param intfname: Interface name
        :param intfmac: Interface MAC address

        :type staname: str
        :type intfname: str
        :type intfmac: str
        """
        self.__staname = staname
        self.__intfname = intfname
        self.__intfmac = intfmac

    def get_station_name(self):
        """
        Get the name of the station

        :rtype: str
        """
        return self.__staname

    def get_intf_name(self):
        """
        Get the interface name

        :rtype: str
        """
        return self.__intfname

    def get_intf_mac(self):
        """
        Get the MAC address of the interface

        :rtype: str
        """
        return self.__intfmac

    def identifier(self):
        """
        Identifier used in dicts

        :return: str
        """
        return self.get_station_name() + "." + self.get_intf_name()


class DynamicWmediumdIntfRef(StaticWmediumdIntfRef):
    def __init__(self, sta, intf):
        """
        An unambiguous reference to an interface of a station

        :param sta: Mininet-Wifi station
        :param intf: Mininet interface

        :type sta: Station
        :type intf: Intf
        """
        super(DynamicWmediumdIntfRef, self).__init__('', '', '')
        self.__sta = sta
        self.__intf = intf
        self.__cachedmac = None

    def get_station_name(self):
        return self.__sta.name

    def get_intf_name(self):
        return self.__intf.name

    def get_intf_mac(self):
        """
        Gets the MAC address of an interface of a station through ifconfig

        :return: The MAC address
        :rtype: str
        """
        if not self.__cachedmac:
            output = self.__sta.cmd(['ifconfig', self.__intf.name, '|', 'grep', '-o', '-E',
                                     '\'([[:xdigit:]]{1,2}:){5}[[:xdigit:]]{1,2}\''])
            self.__cachedmac = output.strip()
        return self.__cachedmac
