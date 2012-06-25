#!/usr/bin/python
# -*- coding: utf-8 -*-
from java.lang import System
import java.util as util
import java.io as javaio
from net.grinder.script.Grinder import grinder
from net.grinder.plugin.http import HTTPPluginControl, HTTPRequest
from net.grinder.script import Test
from HTTPClient import NVPair
from com.redhat.qe.tools import SSHCommandRunner
import time
import re

connectionDefaults = HTTPPluginControl.getConnectionDefaults()
httpUtilities = HTTPPluginControl.getHTTPUtilities()

# connectionDefaults.setFollowRedirects(True)
# connectionDefaults.setUseCookies(True)
connectionDefaults.defaultHeaders = \
        [ NVPair('Accept-Language', 'en-us,en;q=0.5'),
          NVPair('Accept-Encoding', 'gzip, deflate'),
          NVPair('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64; rv:13.0) Gecko/20100101 Firefox/13.0'), ]

buildTest = Test(1, "Build")
pushTest = Test(2, "Push")

# Read the props from automatjon.properties in $HOME
props = util.Properties()
propertiesfis = javaio.FileInputStream("%s/automatjon.properties" % (System.getProperties()['user.home']))
props.load(propertiesfis)

# Update with any system properties passed. These will override the propfile
systemProps = System.getProperties()
props = systemProps
props.update(systemProps)
protocol = props['conductor.protocol']
hostname = props['conductor.hostname']
port = props['conductor.port']
cleanConductorDb = props['conductor.cleardb'] 
serverUsername = props['conductor.ssh.username']
serverPassword = props['conductor.ssh.password']
numusers = props['conductor.grinder.numusers']
profiles = props['conductor.grinder.profiles']

requestURL = "%s://%s:%d" % (protocol, hostname, port)

request1 = HTTPRequest(url=requestURL)
request2 = HTTPRequest(url=requestURL)

templateStr = r'/conductor/images/(.+?)">redirected'
templateRe = re.compile(templateStr)

pushStr = r'Push all'
pushRe = re.compile(pushStr)

buildStr = r'action="(.+?)"  class="button_to"><div><input class="upload_image'
buildRe = re.compile(buildStr)

class BaseTest:
    def __init__(self, request):
        self.request = request

    def establishUserSession(self, user):
        self.token_utf8 = '✓'
        return self.request.POST("/conductor/user_session", (NVPair("authenticity_token", self.authenticity_token),
                                                             NVPair("utf8", self.token_utf8),
                                                             NVPair("login", user),
                                                             NVPair("password", user),
                                                             NVPair("_password", user) 
                                                            ))
    

class BuildSystemTest(BaseTest):
    def execute(self):
        user = "user%d" % (grinder.threadNumber + 1)
        grinder.logger.info("Get login page")
        response = self.request.GET("/conductor/login")
        self.token_utf8 = httpUtilities.valueFromHiddenInput('utf8')
        self.authenticity_token = httpUtilities.valueFromHiddenInput('authenticity_token')
        grinder.logger.info("Establish user session")
        response = self.establishUserSession(user)
        grinder.logger.info("Get root page")
        response = self.request.GET("/conductor")
        grinder.logger.info("Open users page")
        response = self.request.GET("/conductor/users")
        grinder.logger.info("Open pool families page")
        response = self.request.GET("/conductor/pool_families")
        grinder.logger.info("Get new image page")
        response = self.request.GET("/conductor/images/new", (NVPair("environment", "1"),))
        grinder.logger.info("Create new image")
        response = self.request.POST("/conductor/images/edit_xml", (NVPair("authenticity_token", self.authenticity_token),
                                                               NVPair("environment", "1"),
                                                               NVPair("name", "f15-%s" % (user)),
                                                               NVPair("commit", "Continue")
                                                              ))
        grinder.logger.info("Post new image")
        imagexml = """<?xml version="1.0"?><template><name>%s</name><description>foo</description><os><name>Fedora</name><arch>x86_64</arch><version>15</version><install type="url"><url>http://download.fedoraproject.org/pub/fedora/linux/releases/15/Fedora/x86_64/os/</url></install><rootpw>changeme</rootpw></os></template>"""
        imagename = "f15-%s" % (user)
        response = self.request.POST("/conductor/images", (NVPair("authenticity_token", self.authenticity_token),
                                                      NVPair("environment", "1"),
                                                      NVPair("name", imagename),
                                                      NVPair("image_xml", imagexml % (imagename)),
                                                      NVPair("save", "Save+Template")
                                                     ), (), True)
        grinder.logger.info(response.getText())
        image_id = re.search(templateRe, response.getText()).group(1)
        response = self.request.GET("/conductor/images/%s" % (image_id))
        response = self.request.POST("/conductor/images/%s/rebuild_all" % (image_id), (NVPair("authenticity_token", self.authenticity_token),))
        build_not_done = True
        pushUrl = ''
        while build_not_done:
            time.sleep(30)
            response = self.request.GET("/conductor/images/%s" % (image_id))
            if re.search(pushRe, response.getText()):
                pushUrl = re.search(buildRe, response.getText()).group(1)

                build_not_done = False
        return pushUrl

class PushSystemTest(BaseTest):
    def execute(self, pushUrl):
        user = "user%d" % (grinder.threadNumber + 1)
        grinder.logger.info("Get login page")
        response = self.request.GET("/conductor/login")
        self.token_utf8 = httpUtilities.valueFromHiddenInput('utf8')
        self.authenticity_token = httpUtilities.valueFromHiddenInput('authenticity_token')
        response = self.establishUserSession(user)
        grinder.logger.info(pushUrl)
        response = self.request.POST(pushUrl, (NVPair("authenticity_token", self.authenticity_token),))

def setUp():
    sshCommandRunner = SSHCommandRunner(hostname, serverUsername, serverPassword, "cat /home/aeolus-performance-testing/README ")
    if cleanConductorDb:
        sshCommandRunner.run()
        readme = sshCommandRunner.getStdout().strip()
        if readme.find("performance of aeolus"):
            sshCommandRunner.runCommandAndWait("rm -rf /home/aeolus-performance-testing")
        else:
            print "no aeolus-performance-testing directory exists"
        print "cloning aeolus-performance-testing repo"
        sshCommandRunner.runCommandAndWait("cd /home; git clone https://github.com/aeolusproject/aeolus-performance-testing.git")
        print "Creating users"
        sshCommandRunner.runCommandAndWait("/home/aeolus-performance-testing/jmeter/scripts/configure-and-create-users.sh -u %d -p %s" % (numusers, profiles))
    else:
        print "Not creating any new users"


buildSystemTest = BuildSystemTest(request=request1)
pushSystemTest = PushSystemTest(request=request2)
# buildTest.record(buildSystemTest)
# pushTest.record(pushSystemTest)
buildTest.record(request1)
pushTest.record(request2)

setUp()

class TestRunner:
    def __init__(self):
        # Each worker thread joins the barrier.
        self.phase1CompleteBarrier = grinder.barrier("Phase 1")
    
    def __call__(self):
        url = buildSystemTest.execute()
        self.phase1CompleteBarrier.await()
        pushSystemTest.execute(url)

def writeToFile(text):
    filename = "%s-page-%d.html" % (grinder.processName, grinder.runNumber)

    file = open(filename, "w")
    print >> file, text
    file.close()

