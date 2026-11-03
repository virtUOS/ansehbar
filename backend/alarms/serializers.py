# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from rest_framework import serializers

from alarms.models import AlarmRecipient


class AlarmRecipientSerializer(serializers.ModelSerializer):
    # `email` is optional on input: with `user` it is taken from the user.
    email = serializers.EmailField(required=False)
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True
    )
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = AlarmRecipient
        fields = [
            "id", "email", "user", "display_name", "active", "created_at", "created_by",
        ]
        read_only_fields = ["id", "display_name", "created_at", "created_by"]

    def get_display_name(self, obj) -> str:
        user = obj.user
        return (user.get_full_name() or user.get_username()) if user else ""

    def validate(self, attrs):
        if self.instance is not None:
            # Only `active` is editable after creation.
            return {k: v for k, v in attrs.items() if k == "active"}
        user = attrs.get("user")
        if user is not None:
            if not user.email:
                raise serializers.ValidationError(
                    {"user": _("This user has no e-mail address.")}
                )
            attrs["email"] = user.email
        elif not attrs.get("email"):
            raise serializers.ValidationError(
                {"email": _("Provide an e-mail address or a user.")}
            )
        attrs["email"] = attrs["email"].strip().lower()
        if AlarmRecipient.objects.filter(email__iexact=attrs["email"]).exists():
            raise serializers.ValidationError(
                {"email": _("This e-mail address is already a recipient.")}
            )
        return attrs
