from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import ugettext as _
import datetime
from askbot import const
from django.core.urlresolvers import reverse

class BadgeData(models.Model):
    """Awarded for notable actions performed on the site by Users."""
    slug = models.SlugField(max_length=50, unique=True)
    awarded_count = models.PositiveIntegerField(default=0)
    awarded_to    = models.ManyToManyField(User, through='Award', related_name='badges')

    def _get_meta_data(self):
        """retrieves badge metadata stored 
        in a file"""
        from askbot.models import badges
        try:
            return badges.get_badge(self.slug)
        except KeyError:
            #return a dummy badge
            return badges.Badge(level = const.BRONZE_BADGE)

    def is_real_badge(self):
        """true if badge with a given slug exists
        todo: may need attention - currently some badge data is defined in a file,
        and some in the database. Data in the file is considered
        more up to date. It is possifle that the file is edited,
        and data is not deleted from the database, this method
        will find such condition.

        The reason why some data is on disk, is that each 
        badge has code associated with them, that code is not stored in the database.
        Therefore maintenance of badge data requires more attention...
        """
        from askbot.models import badges
        try:
            badges.get_badge(self.slug)
            return True
        except KeyError:
            return False

    @property
    def name(self):
        return self._get_meta_data().name

    @property
    def description(self):
        return self._get_meta_data().description

    @property
    def css_class(self):
        return self._get_meta_data().css_class

    def get_type_display(self):
        #todo - rename "type" -> "level" in this model
        return self._get_meta_data().get_level_display()

    class Meta:
        app_label = 'askbot'
        ordering = ('slug',)

    def __unicode__(self):
        return u'%s: %s' % (self.get_type_display(), self.slug)

    def get_absolute_url(self):
        return '%s%s/' % (reverse('badge', args=[self.id]), self.slug)

class AwardManager(models.Manager):
    def get_recent_awards(self):
        awards = super(AwardManager, self).extra(
            select={'badge_id': 'badge.id', 'badge_name':'badge.name',
                          'badge_description': 'badge.description', 'badge_type': 'badge.type',
                          'user_id': 'auth_user.id', 'user_name': 'auth_user.username'
                          },
            tables=['award', 'badge', 'auth_user'],
            order_by=['-awarded_at'],
            where=['auth_user.id=award.user_id AND badge_id=badge.id'],
        ).values('badge_id', 'badge_name', 'badge_description', 'badge_type', 'user_id', 'user_name')
        return awards

class Award(models.Model):
    """The awarding of a Badge to a User."""
    user       = models.ForeignKey(User, related_name='award_user')
    badge      = models.ForeignKey(BadgeData, related_name='award_badge')
    content_type   = models.ForeignKey(ContentType)
    object_id      = models.PositiveIntegerField()
    content_object = generic.GenericForeignKey('content_type', 'object_id')
    awarded_at = models.DateTimeField(default=datetime.datetime.now)
    notified   = models.BooleanField(default=False)

    objects = AwardManager()

    def __unicode__(self):
        return u'[%s] is awarded a badge [%s] at %s' % (self.user.username, self.badge.name, self.awarded_at)

    class Meta:
        app_label = 'askbot'
        db_table = u'award'

class ReputeManager(models.Manager):
    def get_reputation_by_upvoted_today(self, user):
        """
        For one user in one day, he can only earn rep till certain score (ep. +200)
        by upvoted(also subtracted from upvoted canceled). This is because we need
        to prohibit gaming system by upvoting/cancel again and again.
        """
        if user is None:
            return 0
        else:
            today = datetime.date.today()
            tomorrow = today + datetime.timedelta(1)
            rep_types = (1,-8)
            sums = self.filter(models.Q(reputation_type__in=rep_types),
                                user=user, 
                                reputed_at__range=(today, tomorrow),
                      ).aggregate(models.Sum('positive'), models.Sum('negative'))            
            if sums:
                pos = sums['positive__sum']
                neg = sums['negative__sum']
                if pos is None:
                    pos = 0
                if neg is None:
                    neg = 0
                return pos + neg
            else:
                return 0

class Repute(models.Model):
    """The reputation histories for user"""
    user     = models.ForeignKey(User)
    #todo: combine positive and negative to one value
    positive = models.SmallIntegerField(default=0)
    negative = models.SmallIntegerField(default=0)
    question = models.ForeignKey('Post', null=True, blank=True)
    reputed_at = models.DateTimeField(default=datetime.datetime.now)
    reputation_type = models.SmallIntegerField(choices=const.TYPE_REPUTATION)
    reputation = models.IntegerField(default=1)

    #comment that must be used if reputation_type == 10
    #assigned_by_moderator - so that reason can be displayed
    #in that case Question field will be blank
    comment = models.CharField(max_length=128, null=True)
    
    objects = ReputeManager()

    def __unicode__(self):
        return u'[%s]\' reputation changed at %s' % (self.user.username, self.reputed_at)

    class Meta:
        app_label = 'askbot'
        db_table = u'repute'

    def get_explanation_snippet(self):
        """returns HTML snippet with a link to related question
        or a text description for a the reason of the reputation change

        in the implementation description is returned only 
        for Repute.reputation_type == 10 - "assigned by the moderator"

        part of the purpose of this method is to hide this idiosyncracy
        """
        if self.reputation_type == 10:#todo: hide magic number
            return  _('<em>Changed by moderator. Reason:</em> %(reason)s') \
                                                    % {'reason':self.comment}
        else:
            delta = self.positive - self.negative
            link_title_data = {
                                'points': abs(delta),
                                'username': self.user.username,
                                'question_title': self.question.thread.title
                            }
            if delta > 0:
                link_title = _(
                                '%(points)s points were added for %(username)s\'s '
                                'contribution to question %(question_title)s'
                            ) % link_title_data
            else:
                link_title = _(
                                '%(points)s points were subtracted for %(username)s\'s '
                                'contribution to question %(question_title)s'
                            ) % link_title_data

            return '<a href="%(url)s" title="%(link_title)s">%(question_title)s</a>' \
                            % {
                               'url': self.question.get_absolute_url(), 
                               'question_title': self.question.thread.title,
                               'link_title': link_title
                            }
