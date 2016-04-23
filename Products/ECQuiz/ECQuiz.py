# -*- coding: utf-8 -*-
#
# $Id: ECQuiz.py 251338 2012-10-31 16:31:52Z amelung $
#
# Copyright � 2004-2011 Otto-von-Guericke-Universit�t Magdeburg
#
# This file is part of ECQuiz.
#
# ECQuiz is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# ECQuiz is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ECQuiz; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA

#import os, os.path
import re

from AccessControl import ClassSecurityInfo, getSecurityManager
from Acquisition import aq_parent

from Products.Archetypes.utils import shasattr
from DateTime import DateTime
from zipfile import ZipFile

from Products.Archetypes.public import Schema, BooleanField, StringField
from Products.Archetypes.Widget import TypesWidget, BooleanWidget, SelectionWidget
from Products.Archetypes.utils import DisplayList
from Products.CMFCore.utils import getToolByName

from Products.CMFPlone.i18nl10n import ulocalized_time

from Products.DataGridField.DataGridField import DataGridField
from Products.DataGridField.DataGridWidget import DataGridWidget
from Products.DataGridField.Column import Column

from Products.ECQuiz import config
from Products.ECQuiz import permissions
from Products.ECQuiz.ECQAbstractGroup import ECQAbstractGroup
#from Products.ECQuiz.QuestionTypes.ECQMCQuestion import ECQMCQuestion
from Products.ECQuiz.ECQGroup import ECQGroup
from Products.ECQuiz.ECQReference import ECQReference
from Products.ECQuiz import tools
from Products.ECQuiz.qti import importAssessmentItem, importPackage, exportPackage
from Products.ECQuiz.ECQResult import ECQResult, createResult

from Products.ECQuiz.Statistics import Statistics

#from Products.validation import validation
#from Products.validation import ValidationChain
#from Products.validation.exceptions import ValidatorError

from Products.ECQuiz import log
#from Products.ECQuiz.wikitool import importQuiz,exportQuiz,convertQuiz,updateQuiz
from Products.ECQuiz import wikitool


from Products.ECQuiz.ECQConverterTool import CSVConverter


class DataGridWidgetI18N(DataGridWidget):
    def getColumnLabels(self, field, whatever=None):
        """ Get user friendly names of all columns """

        names = []

        for id in field.getColumnIds():
            # Warn AT developer about his/her mistake
            if not self.columns.has_key(id):
                raise AttributeError, "DataGridWidget missing column definition for " + id + " in field " + field.getName()

            col = self.columns[id]
            names.append(col.getLabel(None,self))

        return names

class ColumnI18N(Column):
    def __init__(self, label, default=None, default_method=None, label_msgid=None):
        """ Create a column
        @param label User visible name
        @param label_msgid Message ID that is used to i18n the label
        """
        self.label = label
        self.default = default
        self.default_method = default_method
        
        if label_msgid is None:
            label_msgid = label
        self.label_msgid = label_msgid

    def getLabel(self, context, widget):
        """ User friendly name for the column """
        if hasattr(widget, 'translate'):  # runtime
            return widget.translate(
                    msgid   = self.label_msgid,
                    domain  = widget.i18n_domain,
                    default = self.label)
        # XXX Fixme this fix dodges the AttributeError: translate problem
        else:  # tests
            return self.label #"what should be here"

class EvaluationScriptsWidget(TypesWidget):
    """ A custom widget for handling the 'evaluationScripts' 
        property of the ECQuiz.
    """
    _properties = TypesWidget._properties.copy()
    _properties.update({
        'macro' : 'evaluation_scripts_widget',
    })


class ECQuiz(ECQAbstractGroup):
    """Debugging only"""
    """This is the main class of the 'ECQuiz' Product.  An ECQuiz is
    basically a folder that contains questions and groups of
    questions, i.e. folders that contain questions."""

    __implements__ = (ECQAbstractGroup.__implements__)

    # format: [file extension, column delimiter, row delimiter, 
    # start of text delimiter, end of text delimiter, escape char]
    RESULTS_EXPORT_FORMAT_TAB = ['tab', '\t', '\n', '"', '"', '"']
    RESULTS_EXPORT_FORMAT_CSV = ['csv', ';',  '\n', '"', '"', '"']
    RESULTS_EXPORT_FORMATS = [RESULTS_EXPORT_FORMAT_TAB, RESULTS_EXPORT_FORMAT_CSV]
    
    # See comments in 'ECQAbstractGroup' for an explanation
    # of the function of a schema, therein defined properties (fields) and 
    # internationalization of the widgets
    schema = ECQAbstractGroup.schema.copy() + Schema((
            BooleanField('instantFeedback',
                         # Instant feedback means that the candidate will see
                         # their results immediately after submitting their
                         # quiz.
                         required=False,
                         default=0,
                         accessor='isInstantFeedback',
                         widget=BooleanWidget(
                             label='Instant Feedback',
                             label_msgid='instant_feedback_label',
                             description='If you want to give the candidates '
                             'instant feedback check this box.',
                             description_msgid='instant_feedback_tool_tip',
                             i18n_domain=config.I18N_DOMAIN),
                         read_permission=permissions.PERMISSION_STUDENT,
                         languageIndependent=True,
            ),
            BooleanField('allowRepetition',
                         # See 'description' of the widget.
                         required=False,
                         default=0,
                         accessor='isAllowRepetition',
                         widget=BooleanWidget(
                             label='Allow Repetition',
                             label_msgid='allow_repetition_label',
                             description='If you want to allow repeated '
                             'submission of the quiz check this box.',
                             description_msgid='allow_repetition_tool_tip',
                             i18n_domain=config.I18N_DOMAIN),
                         read_permission=permissions.PERMISSION_STUDENT,
                         languageIndependent=True,
            ),
            BooleanField('onePerPage',
                         required=False,
                         default=True,
                         accessor='isOnePerPage',
                         widget=BooleanWidget(
                             label='One Question per Page',
                             label_msgid='one_per_page_label',
                             description='If checked, each question/'
                             'question group is displayed on a separate page.',
                             description_msgid='one_per_page_tool_tip',
                             i18n_domain=config.I18N_DOMAIN),
                         read_permission=permissions.PERMISSION_STUDENT,
                         languageIndependent=True,
            ),
            BooleanField('onePerPageNav',
                         required=False,
                         default=True,
                         accessor='isOnePerPageNav',
                         widget=BooleanWidget(
                             label='Allow Navigation',
                             label_msgid='one_per_page_nav_label',
                             description="Let's candidates answer questions "
                             "in an arbitrary order when the quiz is in "
                             "one-question-per-page-mode.",
                            description_msgid='one_per_page_nav_tool_tip',
                             i18n_domain=config.I18N_DOMAIN),
                         read_permission=permissions.PERMISSION_STUDENT,
                         languageIndependent=True,
            ),
            StringField('scoringFunction',
                        default='guessing',
                        enforceVocabulary=1,
                        vocabulary=DisplayList((
                            ('guessing', 'Guessing Correction',
                             'scoring_fun_guessing_correction_label'),
                            ('cruel', 'All or Nothing',
                             'scoring_fun_cruel_label'),
                            )),
                        widget=SelectionWidget(
                            label='Scoring Function',
                            label_msgid='scoring_fun_label',
                            description='The way the score for a question '
                            'is calculated.',
                            description_msgid='scoring_fun_tool_tip',
                            i18n_domain=config.I18N_DOMAIN),
                        read_permission=permissions.PERMISSION_STUDENT,
                        validators=('clearWholePointsCache',),
                        write_permission=permissions.PERMISSION_GRADE,
                        languageIndependent=True,
            ),
            DataGridField('gradingScale',
                          mutator = 'setGradingScale',
                          edit_accessor = 'getGradingScaleForEdit',
                          columns = ('grade', 'gradeinfo', 'score', ),
                          widget = DataGridWidgetI18N(
                              columns = {
                                  'grade' :
                                  ColumnI18N(label='Grade',
                                             label_msgid='grade'),
                                  'gradeinfo' :
                                  ColumnI18N(label='Grade info',
                                             label_msgid='gradeinfo'),
                                  'score' :
                                  ColumnI18N(label='Minimum Score',
                                             label_msgid='minscore'),
                                  },
                              label = "Grading Scale",
                              label_msgid = 'grading_scale_label',
                              description = 'Grades are issued according '
                              'to the following scale of point values.  The '
                              'minimum score can be specified as a '
                              'percentage or as an absolute value.  '
                              'Leave the minimum score column of the last row '
                              'empty; this grade will be used for all scores '
                              'which are not covered by one of the other '
                              'entries.',
                              description_msgid = 'grading_scale_tool_tip',
                              i18n_domain = config.I18N_DOMAIN,
                              ),
                          validators=('gradingScale',),
                          write_permission=permissions.PERMISSION_GRADE,
                          #languageIndependent=True,
            ),
            ),)

    typeDescription = "An online quiz."
    typeDescMsgId = 'description_edit_mctest'

    
    #meta_type = 'ECQuiz'             # zope type name
    #portal_type = meta_type          # plone type name
    #archetype_name = 'ECQuiz'        # friendly type name
    
    security = ClassSecurityInfo()

    i18n_domain = config.I18N_DOMAIN

    security.declarePrivate('manage_afterAdd')
    def manage_afterAdd(self, item, container):
        """
        """
        #log("manage_afterAdd: %s, %s" % (item, container))
        ECQAbstractGroup.manage_afterAdd(self, item, container)
        
        # Add local role 'Manager' for the creator so that users can
        # create quizzes without having to be Manager
        creator = self.Creator()
        roles = list(self.get_local_roles_for_userid(creator))
        if 'Manager' not in roles:
            roles.append('Manager')

        # Create a user-defined role ROLE_RESULT_VIEWER.  This role
        # has the View permission in certain states (defined in
        # ECQResultWorkflow).  This can be used for model solutions:
        #
        # (1) Submit a result with the model solution.
        #
        # (2) Use the"Sharing" tab to assign the role
        #     ROLE_RESULT_VIEWER to the users or groups that should be
        #     allowed to view the assignment.
        #
        # Create a user-defined role ROLE_RESULT_GRADER.  The owner of
        # a quiz can use this role to delegate grading to other users.
        
        for role in [permissions.ROLE_RESULT_VIEWER, permissions.ROLE_RESULT_GRADER]:
            if role not in self.valid_roles():
                self.manage_defined_roles('Add Role',
                                          {'role': role})
            # Assign the local roles to the creator
            if role not in roles:
                roles.append(role)

        # Grant the GradeAssignments permission to the "ECAssignment
        # Grader" role.
        self.manage_permission(permissions.PERMISSION_GRADE,
                               roles=[permissions.ROLE_RESULT_GRADER,],
                               acquire=True)
        
        self.manage_setLocalRoles(creator, roles)

    
    security.declarePrivate('syncResults')
    def syncResults(self, action):
        # FIXME: this is a stub
        assert(action in ['move', 'add', 'delete'])
        
        mtool = self.portal_membership
        
        for result in self.getResults():
            # If this is root's result and it is not submitted, delete
            # it.  Otherwise, possibly mark it as invalid.
            ownerId = result.Creator()
            member = mtool.getMemberById(ownerId)
            # If the user could not be found, [member] will be [None]
            # at this point.  This may happen if the quiz is exported
            # via the ZMI and imported into another system.
            if member:
                ownerIsRoot = self.userIsManager(member)
            else:
                ownerIsRoot = False
                
            if ownerIsRoot and (result.hasState('unsubmitted')):
                if mtool.checkPermission(permissions.CMFCorePermissions.DeleteObjects, result):
                    self.manage_delObjects([result.getId()])
                else:
                    log("Can't delete result '%s'" % result)
            elif action != 'move':
                result.tryWorkflowAction('invalidate', ignoreErrors=True)

    security.declarePrivate('getResults')
    def getResults(self, candidateId=None):
        flt = {'portal_type' : ECQResult.portal_type}
        if candidateId is not None:
            flt['Creator'] = candidateId
        return self.contentValues(filter=flt)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'unsetAllCachedPoints')
    def unsetAllCachedPoints(self):
        results = self.getResults()
        for result in results:
            result.unsetAllCachedPoints()


    security.declarePublic('getResultsDict')
    def getResultsDict(self, resultUIDList=None):
        """Collect all results objects that meet all of the following
        criteria:
        
           * if [resultUIDList] is not None, then their UID is in
             [resultUIDList]
             
           * their workflow state is acceptable, i. e. one of
             [acceptableStates]
             
           * [member] has the 'View' permission for them

        @return A dictionary { candidateId : list_of_results }
        """
        
        acceptableStates = ('unsubmitted',
                            'graded',
                            'pending',
                            'superseded',
                            )
        member = self.portal_membership.getAuthenticatedMember()

        results = {}
        
        for res in self.getResults():
            if (((resultUIDList is None) or (res.getId() in resultUIDList))
                and (res.getWorkflowState() in acceptableStates)
                and member.has_permission('View', res)):
                candidateId = res.Creator()
                tmp = results.get(candidateId, [])
                tmp.append(res)
                results[candidateId] = tmp

        return results


    security.declarePublic('haveDetailedScores')
    def haveDetailedScores(self):
        for item in self.getResults():
            if item.hasState('graded'):
                return True
        return False


    def hasSubmitted(self, candidateId):
        """ Find out if a candidate has actually submitted/taken this
        quiz."""
        # log("ECQuiz.hasSubmitted():")
        for item in self.getResults(candidateId):
            if item.getWorkflowState() in ['pending', 'graded', 'superseded']:
                return True
        return False


    security.declarePublic('isEmpty')
    def isEmpty(self):
        return (not self.getQuestionGroups()) and \
               (not self.getAllQuestions())


    def getQuestionGroups(self):
        """ Returns all the ECQGroup elements (no single questions). """
        return [o for o in self.mcContentValues()
                if o.portal_type == ECQGroup.portal_type]


    # This function has to be implemented by classes derived from 
    # ECQAbstractGroup
    security.declarePublic('isPublic')
    def isPublic(self):
        """ Determine whether this quiz has been published. """
        # log('ECQuiz.isPublic():')
        try:
            user = getSecurityManager().getUser()
            showUnpublishedContent = user.has_role('Authenticated') and \
                                     ('Manager' in self.get_local_roles_for_userid(user.getId()) \
                                      or user.has_role('Manager'))

            # log('\tshowUnpublishedContent = %s'
            #     %(str(showUnpublishedContent)))
            if showUnpublishedContent:
                return True
            if self.getWorkflowState() != 'published':
                # log("\t!'published'")
                return False
            
            now            = DateTime()
            startPublished = getattr(self, 'effective_date', None)
            endPublished   = getattr(self, 'expiration_date', None)
            # log('\tnow = ' + str(now) + '')
            # log('\tstartPublished = ' + str(startPublished))
            # log('\tendPublished = ' + str(endPublished))
            if((startPublished != None) and (startPublished > now)):
                # log("\tstartPublished > now")
                return False
            if((endPublished != None) and (now > endPublished)):
                # log("\tnow > endPublished")
                return False
            # log("\treturn True")
            return True
        except:
            # log("ECQuiz.isPublic() failed. An unknown "
            #     "exception occurred.\n")
            # log("\treturn False")
            return False        


    security.declareProtected(permissions.PERMISSION_STUDENT, 'mayResubmit')
    def mayResubmit(self):
        user = getSecurityManager().getUser()
        candidateId = user.getId()
        
        if self.userIsGrader(user):
            return True
        elif self.isPublic():
            if self.isAllowRepetition():
                return True
            else:
                return not self.hasSubmitted(candidateId)
        else:
            return False


    security.declarePublic('userIsGrader')
    def userIsGrader(self, user):
        """
        """
        mctool = getToolByName(self, 'ecq_tool')
        return mctool.userHasOneOfRoles(user,
                                        ('Manager', permissions.ROLE_RESULT_GRADER,),
                                        self)

    
    security.declarePublic('userIsManager')
    def userIsManager(self, user):
        """
        """
        mctool = getToolByName(self, 'ecq_tool')
        return mctool.userHasOneOfRoles(user, ('Manager',), self)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'maybeMakeNewTest')
    def maybeMakeNewTest(self):
        """If the candidate hasn't seen this quiz yet, generate a new
        one.  Otherwise, do nothing."""
        result = self.getCurrentResult()
        if result is None:
            suMode = self.userIsGrader(getSecurityManager().getUser())
            if suMode or self.mayResubmit():
                result = createResult(self)
                for group in [self] + self.getQuestionGroups():
                    group.makeNewTest(result, suMode)
                # Make this un-undoable by the candidate
                tools.makeTransactionUnundoable()
            
        return result


    security.declareProtected(permissions.PERMISSION_STUDENT, 'getCurrentResult')
    def getCurrentResult(self):
        user = getSecurityManager().getUser()
        candidateId = user.getId()
        
        for item in self.getResults(candidateId):
            if item.hasState('unsubmitted'):
                return item
        
        return None

            
    security.declareProtected(permissions.PERMISSION_INTERROGATOR,'unsetCachedQuestionPoints')
    def unsetCachedQuestionPoints(self, question):
        results = self.getResults()
        for result in results:
            result.unsetCachedQuestionPoints(question)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'convertQuiz')
    def convertQuiz(self, quiz):
        return wikitool.convertQuiz(quiz)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'updateQuiz')
    def updateQuiz(self, quiz, wikistyle):
        return wikitool.updateQuiz(quiz, wikistyle)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'importQuiz')
    def importQuiz(self, quiz, filename):
        return wikitool.importQuiz(quiz, filename)


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'exportQuiz')
    def exportQuiz(self, quiz, filename):
        return wikitool.exportQuiz(quiz, filename)


    def getWorkflowState(self):
        """ Determine the Plone workflow state. """
        workflow_tool = getToolByName(self, 'portal_workflow')
        return workflow_tool.getInfoFor(self, 'review_state', None)

        
    # security.declareProtected(PERMISSION_INTERROGATOR, 'getSubmitterIds')
    def getSubmitterIds(self):
        """Return the IDs of the candidates who have actually
        submitted/taken this quiz.
        """
        d = {}
        for item in self.getResults():
            if item.getWorkflowState() in ['pending', 'graded', 'superseded']:
                d[item.Creator()] = True
        return d.keys()


    security.declarePublic('getResultsAsList')
    def getResultsAsList(self, resultUIDList=None):
        """ Routine for exporting candidate results.
            
            @param resultUIDList A list of UIDs of the results you
                want.  If 'resultUIDList' is 'None', all results will be
                returned.
            
            @return A list containing the results as a dictionary (see
                source for details).
                
                The first "result" ('getResultsAsList()[0]') is a
                header row containing the names of the columns
                associated with the keys in the dictionaries
                (e. g. 'Candidate', 'Name', 'Score' etc.).  The actual
                results start at 'getResultsAsList()[1]'.
        """
        
        def formatTime(dateTimeObj):
            # 'ulocalized_time' is a Plone function
            return ulocalized_time(dateTimeObj, long_format = True, context = self)
        
        # log("ECQuiz.getResultsAsList()")
        ecq_tool = getToolByName(self, 'ecq_tool')

        haveGradingScale = self.haveGradingScale()

        # The header row
        retVal = [
            {'result'      : None, # for internal use only, not used for
                                   # export
             'user_id'     : self.translate(msgid   = 'user_id',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'User ID'),
             'full_name'   : self.translate(msgid   = 'candidate',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Candidate'),
             'state'       : self.translate(msgid   = 'State',
                                            domain  = 'plone',
                                             default = 'State'),
             'grade'       : self.translate(msgid   = 'Grade',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Grade'),
             'score'       : self.translate(msgid   = 'test_results_score',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Score'),
             'max_score'   : self.translate(msgid   = 'test_results_max_score',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Max. Score'),
             'time_start'  : self.translate(msgid   = 'started',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Started'),
             'time_finish' : self.translate(msgid   = 'finished',
                                            domain  = config.I18N_DOMAIN,
                                            default = 'Finished'),
             }]
        
        if not haveGradingScale:
            retVal[0].pop('grade')

        # Get the results
        results = self.getResultsDict(resultUIDList=resultUIDList)
        
        # Remove unsubmitted results of candidates that also have
        # submitted results
        for resList in results.values():
            if len(resList) > 1:
                for res in resList:
                    if res.hasState('unsubmitted'):
                        resList.remove(res)
                        break
        
        participants  = results.keys()
        # We only want submitters who are also in the list of participants 
        # (i.e. in [participants])
        submitters = [c for c in self.getSubmitterIds()
                      if c in participants]
        # Participants who have not submitted their quizzes
        nonSubmitters = [c for c in participants
                         if c not in submitters]
        #log("participants: %s\nsubmitters: %s\nnonSubmitters: %s\n"
        #    %(str(participants), str(submitters), str(nonSubmitters)))
        
        # Sort 'participants' so that 'submitters' come first
        submitters.sort(ecq_tool.cmpByName)
        nonSubmitters.sort(ecq_tool.cmpByName)
        participants  = submitters + nonSubmitters

        # The result workflow
        resultWf = self.portal_workflow.getWorkflowById(config.ECMCR_WORKFLOW_ID)

        member = getSecurityManager().getUser()
        memberId = member.getId()
        
        # The content rows
        for participantId in participants:
            for result in results[participantId]:
                state  = result.getWorkflowState()
                stateTitle = resultWf.states[state].title
                i18nStateTitle = self.translate(msgid   = stateTitle,
                                                domain  = 'plone',
                                                default = stateTitle)

                grade = None
                points = None
                possiblePoints = self.getPossiblePoints(result)
                if state != 'unsubmitted':
                    timeFinished = formatTime( result.getTimeFinish() )
                    # If [member] is the owner of the current quiz,
                    # return the points only if he explicitly has the
                    # permission to see them.
                    if ((participantId != memberId)
                        or self.userIsGrader(member)
                        or self.isInstantFeedback()
                        or ecq_tool.userHasOneOfRoles(
                               member,
                               (permissions.ROLE_RESULT_VIEWER,),
                               result)):
                        
                        # I18N floating point numbers is not done
                        # because exportResults.py needs to know that
                        # when it does the CVS export
                        points = self.getCandidatePoints(result)
                        if haveGradingScale:
                            grade = self.getCandidateGrade(result)
                else:
                    timeFinished = self.translate(msgid   = 'not_submitted',
                                                  domain  = config.I18N_DOMAIN,
                                                  default = 'Not submitted')
                
                retVal.append(
                    {'result'      : result,
                     'user_id'     : participantId,
                     'full_name'   : ecq_tool.getFullNameById(participantId),
                     'state'       : i18nStateTitle,
                     'grade'       : grade,
                     'score'       : points,
                     'max_score'   : possiblePoints,
                     'time_start'  : formatTime( result.getTimeStart() ),
                     'time_finish' : timeFinished,
                     })
                if not haveGradingScale:
                    retVal[-1].pop('grade')

        return retVal


    security.declarePrivate('haveGradingScale')
    def haveGradingScale(self):
        for item in self.getGradingScale():
            if item['score'].strip() or item['grade'].strip():
                return True
        return False
        

    #security.declarePrivate('')
    def getCandidateGrade(self, result):
        # (no doc-string to disable publishing)
        #
        # Return the candidate's grade according to the grading scale
        # or None.
        
        points = self.getCandidatePoints(result)
        if (points is not None) and self.haveGradingScale():
            scale = []
            for item in self.getGradingScale():
                d = dict(item)
                
                if d['score'].endswith('%'):
                    num = float((d['score'].split('%'))[0])
                    f = self.computePossiblePoints(result)/100.0 * num
                else:
                    try:
                        f = float(d['score'])
                    except ValueError:
                        f = None
                d['score'] = f
                scale.append(d)

            def comp(a, b):
                xs = a['score']
                bs = b['score']
                if xs is None:
                    return 1
                elif bs is None:
                    return -1
                else:
                    return xs > bs
            
            scale.sort(comp)

            for pair in scale:
                minScore = pair['score']
                if (minScore is None) or (points >= minScore):
                    grade = pair['grade']
                    for conv in int, float:
                        try:
                            return conv(grade)
                        except:
                            pass
                    return grade
        
        return None


    #security.declarePrivate('')
    def getCandidateGradeinfo(self, result):
        # (no doc-string to disable publishing)
        #
        # Return the candidate's grade according to the grading scale
        # or None.
        
        points = self.getCandidatePoints(result)
        if (points is not None) and self.haveGradingScale():
            scale = []
            for item in self.getGradingScale():
                d = dict(item)

                if d['score'].endswith('%'):
                    num = float((d['score'].split('%'))[0])
                    f = self.computePossiblePoints(result)/100.0 * num
                else:
                    try:
                        f = float(d['score'])
                    except ValueError:
                        f = None
                d['score'] = f
                scale.append(d)

            def comp(a, b):
                xs = a['score']
                bs = b['score']
                if xs is None:
                    return 1
                elif bs is None:
                    return -1
                else:
                    return xs > bs
            
            scale.sort(comp)

            for pair in scale:
                minScore = pair['score']
                if (minScore is None) or (points >= minScore):
                    val = pair['gradeinfo'].strip()
                    if val == "":
                        return None
                    return val
        
        return None


    def getDetailedScores(self):
        # no doc string to disable publishing

        ecq_tool = getToolByName(self, 'ecq_tool')
        haveGradingScale = self.haveGradingScale()

        results = {}
        for item in self.getResults():
            if item.hasState('graded'):
                results[item.Creator()] = item
                
        submitters = results.keys()
        submitters.sort(ecq_tool.cmpByName)
        
        table = []

        labels = {}
        for msgid in [('candidate', 'Candidate'),
                      ('grade',     'Grade'),
                      ('test_results_max_score', 'Max. Score'),
                      ('N', 'Number'),
                      ('sample', 'Sample'),
                      ('mean', 'Mean'),
                      ('median', 'Median'),
                      ('stddev', 'Std. Dev.')]:
            labels[msgid[0]] = self.translate(msgid = msgid[0],
                                              domain = config.I18N_DOMAIN,
                                              default = msgid[1])
        
        header    = [(labels['candidate'], '', '')]
        maxScores = [labels['test_results_max_score']]
        if haveGradingScale:
            header.append((labels['grade'], '', ''))
            maxScores.append('')
        
        if results:
            result0 = results.values()[0]
        else:
            result0 = None

        for group in [self] + self.getQuestionGroups():
            header.append((group.title_or_id(),
                           group.archetype_name,
                           group.absolute_url()))
            if result0:
                maxScore = group.getPossiblePoints(result0)
            else:
                maxScore = '-'
            maxScores.append(maxScore)
            
            allQuestions = group.getAllQuestions()
            
            for question in allQuestions:
                header.append((question.title_or_id(),
                               question.portal_type,
                               question.absolute_url()))
                maxScores.append(question.getPoints())
        
        table.append(header)
        
        if not submitters:
            return table
        
        for cand in submitters:
            result = results[cand]
            candRow = [cand]
            if haveGradingScale:
                candRow.append(self.getCandidateGrade(result))

            for group in [self] + self.getQuestionGroups():
                candRow.append(group.getCandidatePoints(result))
                
                allQuestions       = group.getAllQuestions()
                suggestedQuestions = group.getQuestions(result)
                
                for question in allQuestions:
                    if question in suggestedQuestions:
                        val = question.getCandidatePoints(result)
                    else:
                        val = 1000000 # FIXME: what to do in this case?
                    candRow.append(val)
                
            table.append(candRow)
        
        # Prepare statistics
        
        temp = []
        stats_input = []
        for col in range((haveGradingScale and 2) or 1, len(header)):
            for row in table[1:]:
                stats_input.append(row[col])
            temp.append(stats_input)
            stats_input = []
        
        table.append(maxScores)
        
        for analysis in ['mean', 'median', 'stddev']:
            statsRow = [labels[analysis]]
            if haveGradingScale:
                statsRow.append('')
            for set in temp:
                stats = Statistics(set)
                statsRow.append(getattr(stats, analysis))
            table.append(statsRow)

        return table

    security.declarePrivate('computeCandidatePoints')
    def computeCandidatePoints(self, result):
        """ Return how many points the candidate got for this quiz.
            
            @param candidateId the user ID of the candidate whose
            points you want to know.
            
            If a custom evaluation script has been uploaded it will be
            invoked. Otherwise a default method will be used. 
        """
        customScript = self.getEvaluationScript(self.portal_type)
        questions = self.getQuestions(result)
        questionGroups = self.getQuestionGroups()
        if not customScript: # default
            points = 0
            for questionGroup in questionGroups:
                questionGroupCandidatePoints = \
                    questionGroup.getCandidatePoints(result)
                if not tools.isNumeric(questionGroupCandidatePoints):
                    return None
                points = points + questionGroupCandidatePoints
            for question in questions:
                if not shasattr(question, 'getCandidatePoints'):
                    return None
                questionCandidatePoints = \
                    question.getCandidatePoints(result)
                if not tools.isNumeric(questionCandidatePoints):
                    return None
                points = points + questionCandidatePoints
            return points
        else: # custom
            return tools.evalFunString(
                customScript, config.CUSTOM_EVALUATION_FUNCTION_NAME,
                [self, result, questionGroups, questions])


    security.declareProtected(permissions.PERMISSION_GRADE, 'setGradingScale')
    def setGradingScale(self, input):
        """
        Mutator for the `gradingScale' field.  Allows the input of
        localized numbers in the Minimum Score column.
        """
        decimalSeparator = self.translate(msgid = 'fraction_delimiter',
                                          domain = config.I18N_DOMAIN,
                                          default = '.')
        mutated = []
        
        for row in input:
            if row.has_key('score'): # Initially empty
                score = row['score'].strip()
                newrow = row.copy()
                match = re.match('^[0-9]+(\\' + decimalSeparator
                                 + ')?[0-9]*\s*%?$', score)
                if match:
                    score = score.replace(decimalSeparator, '.')
                    newrow['score'] = score

                mutated.append(newrow)

        self.getField('gradingScale').set(self, mutated)


    def getGradingScaleForEdit(self):
        """
        Edit accessor for the `gradingScale' field. Converts the
        stored minimum score to localized representation.
        """
        stored_data = self.getGradingScale()
        mctool      = getToolByName(self, 'ecq_tool')
        for_edit    = []

        for row in stored_data:
            newrow = row.copy()
            score  = row['score']
            
            match = re.match('^([0-9.]+)(\s*%)?$', score)
            if match:
                number = match.group(1)
                prec = 0
                if number.find('.') > 0:
                    prec = len(number) - number.find('.') - 1

                newrow['score'] = mctool.localizeNumber('%.*f',
                                                        (prec, float(number)))
                if (match.group(2)):
                    newrow['score'] += match.group(2)
            
            for_edit.append(newrow)
        
        return for_edit


    security.declarePublic('isTutorGraded')
    def isTutorGraded(self, result):
        for grp in [self] + self.getQuestionGroups():
            if grp is self:
                if ECQAbstractGroup.isTutorGraded(grp, result):
                    return True
            elif grp.isTutorGraded(result):
                return True
        return False
            

    def getLatestSubmission(self, candidateId):
        retVal = None
        for item in self.getResults(candidateId):
            if ((not item.hasState('invalid')) and
                ((not retVal) or item.isMoreFinal(retVal))):
                retVal = item
        if not retVal:
            raise Exception('Found no submission for %s', repr(candidateId))
        return retVal


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'processQTIImport')
    def processQTIExport(self):
        """ Routine for downloading quizzes.
        """
        errors = tools.MyStringIO()
        package = exportPackage(self, errors)
        # Reset the read ptr of the StringIO obj
        errors.seek(0)
        errorString = errors.read().strip()
        # log(errorString)
        return package, ([errorString, None][not errorString])


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'processQTIImport')
    def processQTIImport(self, file):
        """Routine for uploading quizzes.
        
        @param file: A file containing a QTI assessmentItem or
                     a QTI package in a zip file.
        """
        addedObjects = []
        #errorString = ''
        errors = tools.MyStringIO()

	# custom code --> maybe CSV
	# reset the file read ptr first

	qpackage = None
	try:
                title = self.unicodeDecode(self.Title())
		xmlcsv = CSVConverter(
                      file.read(),
                      title
                      )
            
		qpackage = xmlcsv.generateZippedQuestions()
	except:
		try:
			xmlcsv = CSVConverter(file.filename.read())
			qpackage = xmlcsv.generateZippedQuestions()
		except:
			pass	
	       
	# try zipfile first
        zipFileInstance = None
        try:
		if qpackage != None:
			zipFileInstance = qpackage
		else:
			zipFileInstance = ZipFile(file.filename)
        except:
            try:
		if qpackage != None:
			zipFileInstance = qpackage
		else:
	                zipFileInstance = ZipFile(file)
            except:
                pass
        if(zipFileInstance):
            # is a zip file
            addedObjects = importPackage(self, zipFileInstance, errors)
        else:
            # no zipfile --> maybe XML?
            # reset the file read ptr first
            try:
                file.seek(0)
            except:
                try:
                    file.filename.seek(0)
                except:
                    pass
            string = None
            try:
                string = file.filename.read()
            except:
                try:
                    string = file.read()
                except:
                    pass
            if type(string) not in [str, unicode]:
                # give up, no XML either
                # The file could not be read.
                errors.write( '\n' + self.translate(
                    msgid   = 'file_read_error',
                    domain  = config.I18N_DOMAIN,
                    default = 'The file could not be read.') )
            else:
                # is an XML file
                addedObjects = importAssessmentItem(self, string, errors)
        # Reset the read ptr of the StringIO obj
        errors.seek(0)
        errorString = errors.read().strip()
        # log(errorString)
        return addedObjects, ([errorString, None][not errorString])


    security.declarePrivate('computePossiblePoints')
    def computePossiblePoints(self, result):
        """Return how many points the candidate could have got.
            
        @param candidateId: The user ID of the candidate whose points you 
                            want to know. 
        """
        points = ECQAbstractGroup.computePossiblePoints(self, result)
        if not tools.isNumeric(points):
            return None
        questionGroups = self.getQuestionGroups()
        for questionGroup in questionGroups:
            questionGroupPoints = questionGroup.getPossiblePoints(result)
            if not tools.isNumeric(questionGroupPoints):
                return None
            points += questionGroupPoints
        return points


    security.declareProtected(permissions.PERMISSION_GRADE, 'getItemStatisticsW')
    def getItemStatisticsW(self, candidateIdList = None):
        """Routine for exporting detailed candidate results.
            
        @return: A list of containing the results as a list of values. The
                 values appear in the following order:
                
                 [CandidateID, Candidate_Name] followed by either -, 0 or 1 for
                 each answer to each question in each question group in the
                 quiz.
                
                 "-" means the candidate did not have this answer presented to
                 him/her as a possibility, "0 "means he/she did see this answer
                 but did not check it and "1" means he/she did check it.
                
                 The first three "results" are header rows.
        
        @see: ecq_quiz_statistics.cpt (debugging only)
        """
        ecq_tool = getToolByName(self, 'ecq_tool')

        # The header row
        retVal = []
        h1 = ['', '']
        h2 = ['', '']
        h3 = [self.translate(msgid = 'candidate',
                             domain  = config.I18N_DOMAIN,
                             default = 'Candidate'),
              self.translate(msgid = 'name',
                             domain  = config.I18N_DOMAIN,
                             default = 'Name')]
        for group in [self] + self.getQuestionGroups():
            h1.append([group.title_or_id(),
                       self.translate(msgid = 'ungrouped',
                                      domain  = config.I18N_DOMAIN,
                                      default = '(Ungrouped)')
                       ][group is self])
            allQuestions = group.getAllQuestions()
            #numQuestions = len(allQuestions)
            for question in allQuestions:
                numAnswers = len(question.listFolderContents())
                h1 += ['' for i in range(numAnswers)]
                h2 += [question.title_or_id()] \
                     + ['' for i in range(numAnswers-1)]
                h3 += ['a%d' % (i+1) for i in range(numAnswers)]
            # we added one placeholder too much in the loop above
            h1 = h1[:-1]
        
        for h in [h1, h2, h3]:
            retVal.append( h )
            
        # The content rows
        submitters = self.getSubmitterIds()
        if candidateIdList is not None:
            # If not all results are requested, filter 'submitters' so that
            # every 'candidateId' in 'submitters' is also in 'candidateIdList'
            submitters = filter((lambda candidateId :
                                 (candidateId in candidateIdList)), submitters)
        submitters.sort()
        NaN           = '-' # Not a number/not available
        for submitterId in submitters:
            row = [submitterId, ecq_tool.getFullNameById(submitterId)]
            for group in [self] + self.getQuestionGroups():
                for question in group.getAllQuestions():
                    sSuggestedAnswerIds = question.getSuggestedAnswerIds(
                        submitterId) or []
                    #log(str(sSuggestedAnswerIds))
                    sCandidateAnswerIds = question.getCandidateAnswer(
                        submitterId) or []
                    #log(str(sCandidateAnswerIds))
                    for answer in question.listFolderContents():
                        aId = answer.getId()
                        row += [
                            [NaN, [0, 1][aId in sCandidateAnswerIds]][
                            aId in sSuggestedAnswerIds]]
            
            retVal.append( row )

        #log(self.unicodeDecode(retVal))

        return retVal
    
    
    def getItemStatisticsTable(self, keepQuestionGroups=False):
        """
        @see: ecq_quiz_statistics.cpt (debugging only)
        """
        data = self.getItemStatistics2(keepQuestionGroups)
        participants  = self.getParticipantIds()
        submitters    = filter((lambda candidateId:
                                (candidateId in participants)),
                               self.getSubmitterIds())
        submitters.sort()

        #
        questions = self.getAllQuestions()

        if keepQuestionGroups:
            questions += self.getQuestionGroups()
        else:
            for group in self.getQuestionGroups():
                questions += group.getAllQuestions()

        infoByQid = {}
        for q in questions:
            if shasattr(q, 'getPoints'):
                infoByQid[q.getId()] = {'max': q.getPoints(),
                                        'title': q.getTitle()}
            else:
                infoByQid[q.getId()] = {'max': 'unknown',
                                        'title': q.getTitle()}
        #

        table = []
        #table.append(['questions'] + data.keys())

        row = ['_items']
        for qid in data.keys():
            row.append(infoByQid[qid]['title'])
        table.append(row)

        row = ['_ids']
        for qid in data.keys():
            row.append(qid)
        table.append(row)

        row = ['_max']
        for qid in data.keys():
            row.append(infoByQid[qid]['max'])
        table.append(row)

        for candidateId in submitters:
            row = [candidateId] + ['-' for i in range(len(data.keys()))]
            
#             for i in range(len(data.keys())):
#                 for submission in data[data.keys()[i]]:
#                     if submission[0] == candidateId:
#                         row[i + 1] = submission[1]

            i=1
            for value in data.values():
                for submission in value:
                    if submission[0] == candidateId:
                        row[i] = submission[1]
                i+=1
            
            table.append(row)
        
        return table


    def getItemStatistics3(self):
        """
        @see: ecq_quiz_statistics.cpt (debugging only)
        """
        participants = self.getParticipantIds()
        table = []

        for group in [self] + self.getQuestionGroups():
            table.append(group.title_or_id)
            allQuestions = group.getAllQuestions()
            #numQuestions = len(allQuestions)
            
            for question in allQuestions:
                numAnswers = len(question.listFolderContents())
                header = [question.title_or_id(), 'N', '-'] + \
                         [str(i + 1) for i in range(numAnswers)] + \
                         ['mean', 'stddev', 'median', 'mode']

                i = 3
                for answer in question.listFolderContents():
                    if answer.isCorrect():
                        header[i] += '*'
                    i += 1
                
                
                submitters = [candId for candId in self.getSubmitterIds()
                              if candId in participants]
                afreqs = [question.title_or_id(), 0, 0] + \
                         [0 for i in range(numAnswers)]
                
                for submitter in submitters:
                    sSuggestedAnswerIds = \
                        question.getSuggestedAnswerIds(submitter) or []
                    
                    sCandidateAnswerIds = \
                        question.getCandidateAnswer(submitter) or []
                    
                    if not sCandidateAnswerIds:
                        afreqs[2] += 1
                    else:
                        afreqs[1] += 1 # Number of candidates

                        i = 3
                        for answer in question.listFolderContents():
                            aid = answer.getId()
                            afreqs[i] += [0, 1][aid in sCandidateAnswerIds]
                            i += 1

                # Prepare statistics
                i = 1
                items = []
                for freq in afreqs[3:]:
                    items.extend([i for n in range(0, freq)])
                    i += 1

                stats = Statistics(items)
                afreqs.append(stats.mean)
                afreqs.append(stats.stddev)
                afreqs.append(stats.median)
                afreqs.append(stats.mode)

                table.append(header)
                table.append(afreqs)
                    
        return table

    def getItemStatistics2(self, keepQuestionGroups=False):
        """
        @see: ecq_quiz_statistics.cpt (debugging only)
        """

        participants  = self.getParticipantIds()
        submitters    = [candId for candId in self.getSubmitterIds() if candId in participants]
        submitters.sort()

        questions = self.getAllQuestions()

        if keepQuestionGroups:
            questions += self.getQuestionGroups()
        else:
            for group in self.getQuestionGroups():
                questions += group.getAllQuestions()

        itemStats = {}
        for q in questions:
            itemStats[q.getId()] = []

        for candidateId in submitters:
            candQuestions = self.getQuestions(candidateId)

            for group in self.getQuestionGroups():
                if keepQuestionGroups:
                    candQuestions += self.getQuestionGroups()
                else:
                    candQuestions += group.getQuestions(candidateId)
            
            for q in candQuestions:
                if hasattr(q, 'getPoints'):
                    max = q.getPoints()                    # Question
                else:
                    max = q.getPossiblePoints(candidateId) # Question group
                
                itemStats[q.getId()].append((candidateId,
                                             q.getCandidatePoints(candidateId),
                                             max))
        
        return itemStats
    
    def getItemStatistics(self, keepQuestionGroups=False):
        """
        @see: ecq_quiz_statistics.cpt (debugging only)
        """
        participants  = self.getParticipantIds()
        submitters    = [candId for candId in self.getSubmitterIds()
                         if candId in participants]
        submitters.sort()

        x = {}
        for candidateId in submitters:
            x[candidateId] = []
            
            questions      = self.getQuestions(candidateId)
            questionGroups = self.getQuestionGroups()
            for q in questions:
                max = q.getPoints()
                x[candidateId].append((q.getTitle(),
                                       q.getCandidatePoints(candidateId),
                                       max))
            for q in questionGroups:
                if keepQuestionGroups:
                    max = q.getPossiblePoints(candidateId)
                    x[candidateId].append((q.getTitle(),
                                           q.getCandidatePoints(candidateId),
                                           max))
                else:
                    contained = q.getQuestions(candidateId)
                    for q in contained:
                        max = q.getPoints()
                        x[candidateId].append((q.getTitle(),
                                               q.getCandidatePoints(candidateId),
                                               max))
        return x


    security.declareProtected(permissions.PERMISSION_INTERROGATOR, 'deleteResultsById')
    def deleteResultsById(self, resultIdList):
        """Deletes all the results whose id is in [resultIdList].
        """
        self.manage_delObjects(resultIdList)


    security.declareProtected(permissions.PERMISSION_GRADE, 'processForm')
    def processForm(self, *args, **kwargs):
        """Hack to allow graders to call edit_view
        """
        return ECQAbstractGroup.processForm(self, *args, **kwargs)


    def hasParticipated(self, candidateId):
        """Find out if a quiz has been generated for candidate
        candidateId.
        """
        return not (not self.getResults(candidateId))
        
    
    # security.declareProtected(PERMISSION_INTERROGATOR, 'getParticipantIds')
    def getParticipantIds(self):
        """Get the IDs of all the candidates for whom a quiz has been
        generated.
        """
        d = {}
        for r in self.getResults():
            d[r.Creator()] = True
        return d.keys()


    def __bobo_traverse__(self, REQUEST, name):
        """Through this function, images, files, etc. that were
        referenced by ECQReference objects in the quiz get
        found.

        It works by searching for the files in this quiz ('self') and
        in every quiz from which some question or question group was
        referenced.
        """
        try:
            if REQUEST.has_key('ACTUAL_URL'):
                referencedObjects = self.getReferencedObjects()
                tests = self.getTests(referencedObjects)
                #log("TESTS: %s" % str(tests))
                
                # we only need to do something if we got any new tests
                if tests:
                    # first, search in 'self', then try the others
                    tests = [self] + tests
                    # collect the values that need replacing
                    repl = {}
                    self_url = self.absolute_url()
                    for key in REQUEST.keys():
                        value = REQUEST[key]
                        if (type(value) in [str, unicode]) and \
                               (value.find(self_url) != -1):
                            repl[key] = value
                    
                    # try to get the requested object from one of the
                    # tests in 'tests'
                    for test in tests:
                        # rewrite the URL
                        for key, value in repl.items():
                            REQUEST[key] = value.replace(
                                self_url, test.absolute_url())
                        # try to get the object using the rewritten URL
                        try:
                            result = \
                                ECQAbstractGroup.__bobo_traverse__(
                                    test, REQUEST, name)
                        #except Exception, e:
                            #log("Exception: %s" % str(e))
                        except Exception:
                            result = None
                        # return the object if we got anything
                        if result:
                            return result
        except Exception, e:
            log("ERROR: %s" % str(e))
        
        #except Exception:
        #    pass
            
        return ECQAbstractGroup.__bobo_traverse__(self, REQUEST, name)


    security.declarePrivate('getTests')
    def getTests(self, referencedObjects):
        """Returns a list of the original ECQuizs that the
        objects in 'referencedObjects' come from.
        """
        ret = []
        for o in referencedObjects:
            # Call aq_parent() until we get the ECQuiz
            # that o came from.
            while True:                            
                o = aq_parent(o)
                if o:
                    if o.portal_type == ECQuiz.portal_type:
                        if not o in ret:
                            ret.append(o)
                        break
                else:
                    break
        return ret


#    def __getattr__(self, key):
#        """ 
#        This workaround method maps read requests for the standard 
#        Plone properties 'effective_date'  and 'expiration_date' to
#        calls to  the Archetype  methods  'getEffectiveDate()'  and 
#        'getExpirationDate()',  respectively. This way timed publi-
#        shing/unpublishing works with ECQuizs, too.
#        
#        Consult  the Python  documentation  to  learn  more about
#        '__getattr__()' methods.
#        """
#        if(key == 'effective_date'):
#            return self.getEffectiveDate()
#        elif(key == 'expiration_date'):
#            return self.getExpirationDate()
#        else:
#            raise AttributeError("'%s' object has no attribute '%s'"
#                                 %(repr(self), str(key)) )

#    def validate(self, *args, **kwargs):
#        """Validates the form data from the request.
#        """
#        errors = ECQAbstractGroup.validate(self, *args, **kwargs)
#        
#        # don't know where these come from, but they make the
#        # validation fail for graders
#        for k in ('immediatelyAddableTypes', 'locallyAllowedTypes',):
#            try:
#                errors.pop(k)
#            except:
#                pass
#        return errors


    security.declarePrivate('getReferencedObjects')
    def getReferencedObjects(self):
        """Collect all objects referenced by a ECQReference
        object within this quiz (and its ECQGroups).
        """
        tmp = self.contentValues()
        all = list(tmp)
        for o in tmp:
            if o.portal_type == ECQGroup.portal_type:
                all.extend(o.contentValues())
        return [o.getReference() for o in all
                if o.portal_type == ECQReference.portal_type]



#class ECQuiz2(ECQAbstractGroup):
#        
#    security = ClassSecurityInfo()
#
#    i18n_domain = config.I18N_DOMAIN
    
    def pre_validate(self, REQUEST, errors):
        """This function is called when submitting the edit form (base_edit).
            
        Requests from the 'base_edit' form to delete custom 
        evaluation scripts (from ObjectField 'evaluationScripts') 
        are processed here. 

        @param REQUEST: Contains the input for the form.
        @param errors: If any validation error occurs, put it here.
        """
        if REQUEST.get('deleteCustomEvaluationScripts', []) != []:
            scriptsToBeDeleted = REQUEST.get('deleteCustomEvaluationScripts', [])
            
            if type(scriptsToBeDeleted) != list:
                scriptsToBeDeleted = [scriptsToBeDeleted]
            
            evaluationScripts = self.getEvaluationScripts()
            
            for portal_type in scriptsToBeDeleted:
                if evaluationScripts.has_key(portal_type):
                    evaluationScripts.pop(portal_type)
            
            self.setEvaluationScripts(evaluationScripts)
            
            
    # def post_validate(self, REQUEST, errors):
        # if(REQUEST.get('sourceFile_file', False)):
            # sourceFile = REQUEST.get('sourceFile_file')
            # try:
                # string = sourceFile.filename.read()
            # except:
                # string = sourceFile.read()
            # errorMsg = self.processQTIImport(string)
            # if(errorMsg):
                # errors['sourceFile'] = errorMsg + ' File=' + string
            # self.setSourceFile(None)

            
# Register this type in Zope
tools.registerATCTLogged(ECQuiz)
