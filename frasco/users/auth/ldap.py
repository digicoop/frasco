from frasco.ext import *
from frasco.utils import extract_unmatched_items
from frasco.users.user import signup_user
from frasco.users.auth import register_authentification_handler
from frasco.models import db
import ldap
from ldap.filter import escape_filter_chars
from flask.signals import Namespace as SignalNamespace


_signals = SignalNamespace()
ldap_login = _signals.signal('users_ldap_login')
ldap_signup = _signals.signal('users_ldap_signup')


class LdapTrackUUIDUserModelMixin(object):
    ldap_uuid = db.Column(db.String)


class FrascoUsersLDAP(Extension):
    name = "frasco_users_ldap"
    defaults = {"server": None,
                "use_tls": False,
                "bind_dn": None,
                "bind_password": None,
                "user_dn": '',
                "user_filter": "(&(objectClass=inetOrgPerson)(uid=%(user)s))",
                "username_attr": "uid",
                "append_username_domain": None,
                "strip_username_domain": True,
                "email_attr": "mail",
                "additional_attrs": {},
                "group_flags": {},
                "group_dn": '',
                "group_filter": "(&(objectclass=groupOfNames)(cn=%(group)s))",
                "group_member_attr": "member",
                "group_member_uid_user_attr": None,
                "track_uuid": False,
                "track_uuid_attr": "ldap_uuid"}

    def _init_app(self, app, state):
        register_authentification_handler(self.authentify)

    @ext_stateful_method
    def connect(self, state, bind=True):
        conn = ldap.initialize(state.options['server'])
        ldap_opts = extract_unmatched_items(state.options, self.defaults)
        for key, value in ldap_opts:
            conn.set_option(getattr(ldap, 'OPT_%s' % key), value)
        if bind and state.options['bind_dn']:
            conn.simple_bind_s(state.options['bind_dn'].encode('utf-8'),
                state.options['bind_password'].encode('utf-8'))
        if state.options['use_tls']:
            conn.start_tls_s()
        return conn

    def search_objects(self, base_dn, filter, conn=None):
        if not conn:
            conn = self.connect()
        return conn.search_s(base_dn, ldap.SCOPE_SUBTREE, filter)

    @ext_stateful_method
    def search_user(self, state, id, conn=None):
        filter = state.options['user_filter'] % {'user': escape_filter_chars(id)}
        rs = self.search_objects(state.options['user_dn'], filter, conn)
        if rs:
            return rs[0]

    @ext_stateful_method
    def search_group(self, state, id, conn=None):
        filter = state.options['group_filter'] % {'group': escape_filter_chars(id)}
        rs = self.search_objects(state.options['group_dn'], filter, conn)
        if rs:
            return rs[0]

    @ext_stateful_method
    def is_member_of(self, state, group_dn, user_dn, member_attr=None, conn=None, ignore_errors=True):
        if not conn:
            conn = self.connect()
        if not member_attr:
            member_attr = state.options['group_member_attr']
        try:
            return bool(conn.compare_s(group_dn, member_attr, user_dn))
        except ldap.LDAPError as e:
            if not ignore_errors:
                raise
            return False

    @ext_stateful_method
    def authentify(self, state, username, password):
        try:
            conn = self.connect()
            if state.options['append_username_domain'] and "@" not in username:
                username += "@" + state.options['append_username_domain']
            ldap_user = self.search_user(username, conn=conn)
            if ldap_user:
                dn, attrs = ldap_user
                self.connect(bind=False).simple_bind_s(dn, password)
                return self._get_or_create_user_from_ldap(dn, attrs, conn=conn)
        except ldap.LDAPError as e:
            self.get_app().log_exception(e)

    @ext_stateful_method
    def _get_or_create_user_from_ldap(self, state, dn, attrs, conn=None):
        UserModel = self.get_app().extensions.frasco_users.Model

        if state.options['track_uuid']:
            user = UserModel.query.filter(
                getattr(UserModel, state.options['track_uuid_attr']) == attrs[state.options['track_uuid']][0]).first()
        else:
            user = UserModel.query.filter(UserModel.email == attrs[state.options['email_attr']][0].lower()).first()

        if user:
            ldap_login.send(user=user, dn=dn, attrs=attrs, conn=conn)
            return user

        username = attrs[state.options['username_attr']][0]
        if "@" in username and state.options['strip_username_domain']:
            username = username.split('@')[0]

        user = UserModel()
        user.email = attrs[state.options['email_attr']][0]
        user.username = username
        if state.options['track_uuid']:
            setattr(user, state.options['track_uuid_attr'],
                attrs[state.options['track_uuid']][0])
        for target, src in state.options['additional_attrs'].iteritems():
            if src in attrs:
                setattr(user, target, attrs[src][0])

        memberships = {}
        for flag, group_dn in state.options['group_flags'].iteritems():
            member = getattr(user, state.options['group_member_uid_user_attr'])\
                        if state.options['group_member_uid_user_attr'] else dn
            if group_dn not in memberships:
                memberships[group_dn] = self.is_member_of(group_dn, member, conn=conn)
            setattr(user, flag, memberships[group_dn])

        try:
            signup_user(user, provider='ldap')
        except:
            return

        ldap_signup.send(user=user, dn=dn, attrs=attrs, conn=conn)
        return user
